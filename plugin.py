from __future__ import annotations
from .tarball import decompress, download
from LSP.plugin import __version__ as LSP_VERSION
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
from LSP.plugin.core.protocol import DocumentUri
from LSP.plugin.core.protocol import ExecuteCommandParams
from LSP.plugin.core.protocol import LSPAny
from LSP.plugin.core.protocol import TextDocumentPositionParams
from LSP.plugin.core.typing import NotRequired, StrEnum
from LSP.plugin.core.typing import cast
from typing import Callable, Literal, Tuple, TypedDict
from urllib.parse import unquote, urlparse
from weakref import ref
import os
import sublime
import sublime_plugin


PACKAGE_NAME = 'LSP-Tinymist'
VERSION = 'v0.13.26'
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


class PdfStandard(StrEnum):
    V_1_7 = '1.7'  # PDF 1.7
    A_2b = 'a-2b'  # PDF/A-2b
    A_3b = 'a-3b'  # PDF/A-3b


class ExportOpts(TypedDict):
    fill: NotRequired[str]
    ppi: NotRequired[int]
    open: NotRequired[bool]
    creation_timestamp: NotRequired[str]
    pdf_standard: NotRequired[list[PdfStandard]]
    page: NotRequired[dict]


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
        return f'$ublime-{self._preview_task_id}' if self._preview_task_id else ''

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
        session = self.weaksession()
        if not session:
            return
        elif action == 'preview':
            # TODO: handle multiple open files
            if self.preview_task_id:
                command: ExecuteCommandParams = {
                    'command': 'tinymist.doKillPreview',
                    'arguments': [self.preview_task_id]
                }
                session.execute_command(command, False)
            self._preview_task_id += 1
            command: ExecuteCommandParams = {
                # 'command': 'tinymist.startDefaultPreview',
                'command': 'tinymist.doStartBrowsingPreview',
                # 'command': 'tinymist.doStartPreview',
                'arguments': [['--task-id', self.preview_task_id] + session.config.settings.get('preview.browsing.args')]
            }
            session.execute_command(command, False).then(self._on_preview_result)
        elif action == 'export-pdf':
            view = session.window.active_view()
            if not view:
                return
            filename = view.file_name()
            if not filename:
                return
            export_opts: ExportOpts = {
                'open': True
            }
            command: ExecuteCommandParams = {
                'command': 'tinymist.exportPdf',
                'arguments': [filename, cast(LSPAny, export_opts)]
            }
            session.execute_command(command, False)
        elif action == 'more':
            view = session.window.active_view()
            if not view:
                return
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
        session.execute_command(command, False)

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
            if LSP_VERSION >= (2, 6, 0):  # pyright: ignore[reportOperatorIssue]  # https://github.com/microsoft/pyright/issues/7733
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
        export_opts: ExportOpts = {
            'open': True
        }
        format_ = format.lower()
        command_name = {
            'pdf': 'tinymist.exportPdf',
            'png': 'tinymist.exportPng',
            'svg': 'tinymist.exportSvg',
            'html': 'tinymist.exportHtml',
            'markdown': 'tinymist.exportMarkdown',
            'latex': 'tinymist.exportTeX'
        }.get(format_)
        if not command_name:
            self._status_message(f'Unsupported format {format}')
            return
        if format_ in ('png', 'svg'):
            export_opts['page'] = {'merged': {'gap': '0pt'}}
        command: ExecuteCommandParams = {
            'command': command_name,
            'arguments': [filename, cast(LSPAny, export_opts)]
        }
        session.execute_command(command, False)

    def input(self, args: dict) -> sublime_plugin.ListInputHandler | None:
        if 'command' not in args:
            return ExportFormatInputHandler()

    def _status_message(self, msg: str) -> None:
        window = self.view.window()
        if window:
            window.status_message(msg)


class ExportFormatInputHandler(sublime_plugin.ListInputHandler):

    def name(self) -> str:
        return 'format'

    def list_items(self) -> list[sublime.ListInputItem]:
        formats = ('PDF', 'PNG', 'SVG', 'HTML', 'Markdown', 'LaTeX')
        return [sublime.ListInputItem(f'Export as {fmt}', fmt) for fmt in formats]
