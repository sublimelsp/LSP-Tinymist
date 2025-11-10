from __future__ import annotations
from .tarball import decompress, download
from LSP.plugin import AbstractPlugin
from LSP.plugin import LspTextCommand
from LSP.plugin import parse_uri
from LSP.plugin import register_plugin
from LSP.plugin import Request
from LSP.plugin import Response
from LSP.plugin import Session
from LSP.plugin import unregister_plugin
from LSP.plugin.core.logging import debug
from LSP.plugin.core.open import open_externally
from LSP.plugin.core.typing import NotRequired, StrEnum
from LSP.plugin.core.typing import cast
from LSP.plugin.core.views import first_selection_region
from LSP.plugin.core.views import region_to_range
from LSP.plugin.core.views import text_document_identifier
from LSP.protocol import DocumentUri
from LSP.protocol import ExecuteCommandParams
from LSP.protocol import LSPAny
from LSP.protocol import Range
from LSP.protocol import TextDocumentIdentifier
from LSP.protocol import TextDocumentPositionParams
from LSP.protocol import TextEdit
from functools import partial
from typing import Callable, List, Literal, Tuple, TypedDict, Union
from urllib.parse import unquote, urlparse
from weakref import ref
import os
import sublime
import sublime_plugin


PACKAGE_NAME = 'LSP-Tinymist'
VERSION = 'v0.14.0'
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
    V_1_7 = '1.7'  # PDF 1.7
    A_2b = 'a-2b'  # PDF/A-2b
    A_3b = 'a-3b'  # PDF/A-3b


class ExportPdfOpts(TypedDict):
    pages: NotRequired[list[str]]
    creationTimestamp: NotRequired[str | None]


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
    register_plugin(LspTinymistPlugin)


def plugin_unloaded() -> None:
    unregister_plugin(LspTinymistPlugin)


class LspTinymistPlugin(AbstractPlugin):

    def __init__(self, weaksession: ref[Session]) -> None:
        super().__init__(weaksession)
        self._preview_task_id = 0

    @property
    def preview_task_id(self) -> str:
        return f'preview-{self._preview_task_id}' if self._preview_task_id else ''

    @classmethod
    def name(cls) -> str:
        return PACKAGE_NAME

    @classmethod
    def configuration(cls) -> Tuple[sublime.Settings, str]:
        filename = f'{PACKAGE_NAME}.sublime-settings'
        filepath = f'Packages/{PACKAGE_NAME}/{filename}'
        return sublime.load_settings(filename), filepath

    @classmethod
    def basedir(cls) -> str:
        return os.path.join(cls.storage_path(), PACKAGE_NAME)

    @classmethod
    def additional_variables(cls) -> dict[str, str] | None:
        server_dir = cls.basedir()
        if TARBALL_NAME and TARBALL_NAME.endswith('.tar.gz'):
            server_dir = os.path.join(server_dir, TARBALL_NAME.split('.')[0])
        return {'server_dir': server_dir}

    @classmethod
    def needs_update_or_installation(cls) -> bool:
        try:
            with open(os.path.join(cls.basedir(), 'VERSION'), 'r') as file:
                return file.read().strip() != VERSION
        except OSError:
            return True

    @classmethod
    def install_or_update(cls) -> None:
        if not TARBALL_NAME:
            debug('Prebuilt Tinymist binary is not available for this system.')
            return
        download_url = f'https://github.com/Myriad-Dreamin/tinymist/releases/download/{VERSION}/{TARBALL_NAME}'
        server_dir = cls.basedir()
        tarball_path = os.path.join(server_dir, TARBALL_NAME)
        download(download_url, tarball_path)
        decompress(tarball_path, server_dir)
        with open(os.path.join(cls.basedir(), 'VERSION'), 'w') as file:
            file.write(VERSION)

    def on_server_response_async(self, method: str, response: Response) -> None:
        if method == 'textDocument/codeLens' and response.result:
            del response.result[0]  # Profile

    def on_pre_server_command(self, command: ExecuteCommandParams, done_callback: Callable[[], None]) -> bool:
        command_name = command['command']
        if command_name == 'tinymist.runCodeLens':
            args = command.get('arguments')
            if args:
                action = cast(str, args[0])
                sublime.set_timeout(lambda: self._on_code_lens(action))
            sublime.set_timeout(done_callback)
            return True
        return False

    def _on_code_lens(self, action: str) -> None:
        if session := self.weaksession():
            if action == 'preview':
                if self.preview_task_id:
                    command: ExecuteCommandParams = {
                        'command': 'tinymist.doKillPreview',
                        'arguments': [self.preview_task_id]
                    }
                    session.execute_command(command)
                self._preview_task_id += 1
                command: ExecuteCommandParams = {
                    'command': 'tinymist.doStartBrowsingPreview',
                    'arguments': [['--task-id', self.preview_task_id] + session.config.settings.get('preview.browsing.args')]
                }
                session.execute_command(command).then(self._on_preview_result)
            elif action == 'export-pdf':
                if view := session.window.active_view():
                    view.run_command('lsp_tinymist_export', {'format': 'pdf'})
            elif action == 'more':
                if view := session.window.active_view():
                    view.run_command('lsp_tinymist_export')

    def _on_preview_result(self, params: PreviewResult) -> None:
        pass

    def on_pre_send_request_async(self, request_id: int, request: Request) -> None:
        # Hack into document highlight request to send an additional request to scroll the browser preview when the
        # caret position changes.
        if self.preview_task_id and request.method == 'textDocument/documentHighlight':
            sublime.set_timeout_async(lambda: self.on_caret_moved_async(request.params))

    def on_caret_moved_async(self, position_params: TextDocumentPositionParams) -> None:
        session = self.weaksession()
        if not session:
            return
        scheme, path = parse_uri(position_params['textDocument']['uri'])
        if scheme != 'file':
            return
        position = position_params['position']
        params: PreviewScrollParams = {
            'event': 'panelScrollTo',
            'filepath': path,
            'line': position['line'],
            'character': position['character']
        }
        command: ExecuteCommandParams = {
            'command': 'tinymist.scrollPreview',
            'arguments': [self.preview_task_id, cast(LSPAny, params)]
        }
        session.execute_command(command)

    def on_open_uri_async(self, uri: DocumentUri, callback: Callable[[str | None, str, str], None]) -> bool:
        parsed = urlparse(uri)
        if parsed.scheme == 'command' and parsed.path.startswith('tinymist'):
            command = parsed.path
            scheme, filename = parse_uri(unquote(parsed.query).strip('[]"'))
            if scheme == 'file':
                if command == 'tinymist.openInternal':
                    session = self.weaksession()
                    if session:
                        session.window.open_file(filename)
                elif command == 'tinymist.openExternal':
                    open_externally(filename, True)
            sublime.set_timeout_async(lambda: callback(None, '', ''))
            return True
        return False

    def m_tinymist_compileStatus(self, params: CompileStatusParams) -> None:
        session = self.weaksession()
        if not session:
            return
        status = params['status']
        if status == CompileStatus.COMPILING:
            return  # Don't update the status message to prevent flickering from volatile page count reports.
        # elif status == CompileStatus.COMPILE_SUCCESS:
        #     pass
        # elif status == CompileStatus.COMPILE_ERROR:
        #     pass
        # file = params['path']
        page_count = params['pageCount']
        msg = f'{page_count} page'
        if page_count != 1:
            msg += 's'
        words_count = params['wordsCount']
        if words_count is not None:
            words = words_count['words']
            msg += f', {words} word'
            if words != 1:
                msg += 's'
        session.set_config_status_async(msg)

    def m_tinymist_documentOutline(self, params: DocumentOutlineParams) -> None:
        # The server requests to update the document outline.
        pass

    def m_tinymist_preview_dispose(self, params: PreviewDisposeParams) -> None:
        # The server requests to dispose (clean up) a preview task when it is no longer needed.
        pass


class LspTinymistExportCommand(LspTextCommand):

    session_name = PACKAGE_NAME

    def run(self, edit: sublime.Edit, format: str):  # pyright: ignore[reportIncompatibleMethodOverride]
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
        command_args = cast(List[LSPAny], [filename, extra_opts, actions])
        command: ExecuteCommandParams = {
            'command': command_name,
            'arguments': command_args
        }
        session.execute_command(command).then(self._on_export_result_async)

    def input(self, args: dict) -> sublime_plugin.ListInputHandler | None:
        if 'format' not in args:
            return ExportFormatInputHandler()

    def _on_export_result_async(self, response: ExportResponse) -> None:
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
    session_name = PACKAGE_NAME

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
