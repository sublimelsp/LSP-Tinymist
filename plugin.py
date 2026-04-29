from __future__ import annotations

from .lib.tarball import decompress
from .lib.tarball import download
from LSP.plugin import command_handler
from LSP.plugin import LspPlugin
from LSP.plugin import LspTextCommand
from LSP.plugin import notification_handler
from LSP.plugin import OnPreStartContext
from LSP.plugin import parse_uri
from LSP.plugin import PluginStartError
from LSP.plugin import Promise
from LSP.plugin import Request
from LSP.plugin import ServerResponse
from LSP.plugin import SessionViewProtocol
from LSP.plugin import uri_handler
from LSP.plugin.core.open import open_externally
from LSP.plugin.core.protocol import Error
from LSP.plugin.core.typing import NotRequired
from LSP.plugin.core.typing import StrEnum
from LSP.plugin.core.views import first_selection_region
from LSP.plugin.core.views import position
from LSP.plugin.core.views import region_to_range
from LSP.plugin.core.views import text_document_identifier
from LSP.protocol import DocumentUri
from LSP.protocol import ExecuteCommandParams
from LSP.protocol import Range
from LSP.protocol import TextDocumentIdentifier
from LSP.protocol import TextEdit
from functools import partial
from typing import Any
from typing import cast
from typing import Literal
from typing import TypedDict
from typing import Union
from urllib.parse import unquote
from urllib.parse import urlparse
from uuid import uuid4
import sublime
import sublime_plugin


VERSION = 'v0.14.16'
TARBALL_NAME = {
    'linux-arm64': 'tinymist-aarch64-unknown-linux-gnu.tar.gz',
    'linux-x64': 'tinymist-x86_64-unknown-linux-gnu.tar.gz',
    'osx-arm64': 'tinymist-aarch64-apple-darwin.tar.gz',
    'osx-x64': 'tinymist-x86_64-apple-darwin.tar.gz',
    'windows-arm64': 'tinymist-aarch64-pc-windows-msvc.zip',
    'windows-x64': 'tinymist-x86_64-pc-windows-msvc.zip',
}.get(f'{sublime.platform()}-{sublime.arch()}')


class CompileStatus(StrEnum):
    COMPILING = 'compiling'
    COMPILE_SUCCESS = 'compileSuccess'
    COMPILE_ERROR = 'compileError'


class WordsCount(TypedDict):
    words: int
    chars: int
    spaces: int
    cjkChars: int


class CompileStatusParams(TypedDict):
    status: CompileStatus
    path: str
    pageCount: int
    wordsCount: WordsCount | None


class CursorPosition(TypedDict):
    page_no: int
    x: float
    y: float


class OutlineItemData(TypedDict):
    title: str
    span: NotRequired[str]
    position: NotRequired[CursorPosition]
    children: list[OutlineItemData]


class DocumentOutlineParams(TypedDict):
    items: list[OutlineItemData]


class PreviewResult(TypedDict):
    staticServerAddr: NotRequired[str]
    staticServerPort: NotRequired[int]
    dataPlanePort: NotRequired[int]
    isPrimary: NotRequired[bool]


class PreviewDisposeParams(TypedDict):
    taskId: str


class PreviewScrollParams(TypedDict):
    event: Literal['changeCursorPosition'] | Literal['panelScrollTo']
    filepath: str
    line: int
    character: int


class OnEnterParams(TypedDict):
    textDocument: TextDocumentIdentifier
    range: Range


class PdfStandard(StrEnum):
    V_1_4 = '1.4'  # PDF 1.4
    V_1_5 = '1.5'  # PDF 1.5
    V_1_6 = '1.6'  # PDF 1.6
    V_1_7 = '1.7'  # PDF 1.7
    V_2_0 = '2.0'  # PDF 2.0
    A_1b = 'a-1b'  # PDF/A-1b
    A_1a = 'a-1a'  # PDF/A-1a
    A_2b = 'a-2b'  # PDF/A-2b
    A_2u = 'a-2u'  # PDF/A-2u
    A_2a = 'a-2a'  # PDF/A-2a
    A_3b = 'a-3b'  # PDF/A-3b
    A_3u = 'a-3u'  # PDF/A-3u
    A_3a = 'a-3a'  # PDF/A-3a
    A_4 = 'a-4'    # PDF/A-4
    A_4f = 'a-4f'  # PDF/A-4f
    A_4e = 'a-4e'  # PDF/A-4e
    Ua_1 = 'ua-1'  # PDF/UA-1


class ExportPdfOpts(TypedDict):
    pages: NotRequired[list[str]]
    creationTimestamp: NotRequired[str | None]
    pdfStandard: NotRequired[PdfStandard]
    noPdfTags: NotRequired[bool]


class PageMergeOpts(TypedDict):
    gap: NotRequired[str | None]


class ExportPngOpts(TypedDict):
    pages: NotRequired[list[str]]
    pageNumberTemplate: NotRequired[str]
    merge: NotRequired[PageMergeOpts]
    fill: NotRequired[str]
    ppi: NotRequired[int]


class ExportSvgOpts(TypedDict):
    pages: NotRequired[list[str]]
    pageNumberTemplate: NotRequired[str]
    merge: NotRequired[PageMergeOpts]


class ExportHtmlOpts(TypedDict):
    pass


ExportOpts = Union[ExportPdfOpts, ExportPngOpts, ExportSvgOpts, ExportHtmlOpts]


class ExportActionOpts(TypedDict):
    write: NotRequired[bool]
    open: NotRequired[bool]


class ExportedPage(TypedDict):
    page: int
    path: str | None
    data: str | None


class ExportResponse(TypedDict):
    path: NotRequired[str | None]
    data: NotRequired[str | None]
    totalPages: NotRequired[int]
    items: NotRequired[list[ExportedPage]]


def plugin_loaded() -> None:
    LspTinymistPlugin.register()


def plugin_unloaded() -> None:
    LspTinymistPlugin.unregister()


class LspTinymistPlugin(LspPlugin):

    @classmethod
    def on_pre_start_async(cls, context: OnPreStartContext) -> None:
        if not TARBALL_NAME:
            raise PluginStartError('Prebuilt Tinymist binary is not available for this system.')
        server_path = cls.plugin_storage_path
        if TARBALL_NAME.endswith('.tar.gz'):
            server_path /= TARBALL_NAME.split('.')[0]
        server_dir = str(server_path)
        context.variables['server_dir'] = server_dir
        if cls.needs_installation():
            download_url = f'https://github.com/Myriad-Dreamin/tinymist/releases/download/{VERSION}/{TARBALL_NAME}'
            tarball_path = str(cls.plugin_storage_path / TARBALL_NAME)
            download(download_url, tarball_path)
            decompress(tarball_path, server_dir)
            (cls.plugin_storage_path / 'VERSION').write_text(VERSION)

    @classmethod
    def needs_installation(cls) -> bool:
        try:
            return (cls.plugin_storage_path / 'VERSION').read_text().strip() != VERSION
        except OSError:
            return True

    def on_initialize_async(self) -> None:
        self.preview_task_id: str = ''

    def on_server_response_async(self, response: ServerResponse) -> None:
        if response['method'] == 'textDocument/codeLens':
            if (result := response['result']) and len(result) == 5:
                del result[4]  # More
                del result[0]  # Profile

    @notification_handler('tinymist/compileStatus')
    def on_compile_status(self, params: CompileStatusParams) -> None:
        if session := self.weaksession():
            status = params['status']
            if status == CompileStatus.COMPILING:
                return  # Don't update the status message to prevent flickering from volatile page count reports.
            # elif status == CompileStatus.COMPILE_SUCCESS:
            #     pass
            # elif status == CompileStatus.COMPILE_ERROR:
            #     pass
            # file = params['path']
            page_count = params['pageCount']
            message = f'{page_count} page{"s"[:page_count!=1]}'
            if words_count := params['wordsCount']:
                words = words_count['words']
                message += f', {words} word{"s"[:words!=1]}'
            session.set_config_status_async(message)

    @notification_handler('tinymist/documentOutline')
    def on_document_outline(self, params: DocumentOutlineParams) -> None:
        # The server requests to update the document outline.
        pass

    @notification_handler('tinymist/previewDispose')
    def on_preview_dispose(self, params: PreviewDisposeParams) -> None:
        # The server requests to dispose (clean up) a preview task when it is no longer needed.
        pass

    @uri_handler('command')
    def on_open_command_uri(self, uri: DocumentUri, flags: sublime.NewFileFlags) -> Promise[sublime.Sheet | None]:
        parsed = urlparse(uri)
        scheme, filename = parse_uri(unquote(parsed.query).strip('[]"'))
        if scheme != 'file':
            return Promise.resolve(None)
        command = parsed.path
        if command == 'tinymist.openInternal':
            if session := self.weaksession():
                view = session.window.open_file(filename, flags)
                # Note that in case of an image file the returned View will not be valid and the only way to get the
                # Sheet seems to be via Window.active_sheet().
                sheet = view.sheet() if view.is_valid() else session.window.active_sheet()
                return Promise.resolve(sheet)
            return Promise.resolve(None)
        if command == 'tinymist.openExternal':
            open_externally(filename)
        return Promise.resolve(None)

    @command_handler('tinymist.runCodeLens')
    def on_run_code_lens(self, arguments: list[str] | None) -> Promise[None]:
        if arguments and (session := self.weaksession()):
            action = arguments[0]
            if action == 'preview':
                if self.preview_task_id:
                    command: ExecuteCommandParams = {
                        'command': 'tinymist.doKillPreview',
                        'arguments': [self.preview_task_id]
                    }
                    session.execute_command(command)
                self.preview_task_id = str(uuid4())
                command: ExecuteCommandParams = {
                    'command': 'tinymist.doStartBrowsingPreview',
                    'arguments': [['--task-id', self.preview_task_id] + session.config.settings.get('preview.browsing.args')]
                }
                session.execute_command(command).then(self._on_preview_result)  # pyright: ignore[reportArgumentType]
            elif action == 'export':
                if view := session.window.active_view():
                    view.run_command('lsp_tinymist_export')
            elif action == 'export-pdf':
                if view := session.window.active_view():
                    view.run_command('lsp_tinymist_export', {'format': 'pdf'})
        return Promise.resolve(None)

    def _on_preview_result(self, params: PreviewResult | Error) -> None:
        pass

    def on_selection_modified_async(self, session_view: SessionViewProtocol) -> None:
        if not self.preview_task_id:
            return
        view = session_view.view
        if filepath := view.file_name():
            try:
                point = view.sel()[0].b
            except IndexError:
                return
            pos = position(view, point)
            params: PreviewScrollParams = {
                'event': 'panelScrollTo',
                'filepath': filepath,
                'line': pos['line'],
                'character': pos['character']
            }
            command: ExecuteCommandParams = {
                'command': 'tinymist.scrollPreview',
                'arguments': [self.preview_task_id, params]
            }
            session_view.session.execute_command(command)


class LspTinymistExportCommand(LspTextCommand):

    def run(self, edit: sublime.Edit, format: str) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        filename = self.view.file_name()
        if not filename:
            self._status_message('Export unavailable for unsaved file')
            return
        session = self.session_by_name(self.session_name)
        if not session:
            return
        extra_opts: ExportOpts = {}
        actions: ExportActionOpts = {'open': True}
        fmt = format.lower()
        if fmt == 'pdf':
            command_name = 'tinymist.exportPdf'
            extra_opts = cast(ExportPdfOpts, extra_opts)
        elif fmt == 'png':
            command_name = 'tinymist.exportPng'
            extra_opts = cast(ExportPngOpts, extra_opts)
            extra_opts['merge'] = {'gap': None}
        elif fmt == 'svg':
            command_name = 'tinymist.exportSvg'
            extra_opts = cast(ExportSvgOpts, extra_opts)
            extra_opts['merge'] = {'gap': None}
        elif fmt == 'html':
            command_name = 'tinymist.exportHtml'
            extra_opts = cast(ExportHtmlOpts, extra_opts)
        elif fmt == 'markdown':
            command_name = 'tinymist.exportMarkdown'
        elif fmt == 'latex':
            command_name = 'tinymist.exportTeX'
        else:
            self._status_message(f'Unsupported format {format}')
            return
        command: ExecuteCommandParams = {
            'command': command_name,
            'arguments': [filename, extra_opts, actions]
        }
        session.execute_command(command).then(self._on_export_result_async)  # pyright: ignore[reportArgumentType]

    def input(self, args: dict[str, Any]) -> sublime_plugin.ListInputHandler | None:
        if 'format' not in args:
            return ExportFormatInputHandler()

    def _on_export_result_async(self, response: ExportResponse | Error) -> None:
        pass

    def _status_message(self, msg: str) -> None:
        if window := self.view.window():
            window.status_message(msg)


class ExportFormatInputHandler(sublime_plugin.ListInputHandler):

    def name(self) -> str:
        return 'format'

    def list_items(self) -> list[sublime.ListInputItem]:
        formats = ('PDF', 'PNG', 'SVG', 'HTML', 'Markdown', 'LaTeX')
        return [sublime.ListInputItem(f'Export as {fmt}', fmt) for fmt in formats]


class LspTinymistOnEnterCommand(LspTextCommand):

    capability = 'experimental.onEnter'

    def run(self, edit: sublime.Edit) -> None:
        session = self.session_by_name(self.session_name, self.capability)
        if not session:
            return
        selection_region = first_selection_region(self.view)
        if selection_region is None:
            return
        params: OnEnterParams = {
            'textDocument': text_document_identifier(self.view),
            'range': region_to_range(self.view, selection_region)
        }
        request = Request('experimental/onEnter', params, self.view)
        session.send_request_async(request, partial(self._on_result, self.view.change_count()))

    def _on_result(self, version: int, edits: list[TextEdit] | None) -> None:
        if edits:
            self.view.run_command('lsp_apply_document_edit', {
                'changes': edits,
                'required_view_version': version,
                'process_placeholders': True
            })
        elif version == self.view.change_count():
            self.view.run_command('insert', {'characters': '\n'})
