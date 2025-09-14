from __future__ import annotations
from .tarball import decompress, download
from LSP.plugin import AbstractPlugin
from LSP.plugin import LspTextCommand
from LSP.plugin import register_plugin
from LSP.plugin import Response
from LSP.plugin import Session
from LSP.plugin import unregister_plugin
from LSP.plugin.core.protocol import ExecuteCommandParams
from LSP.plugin.core.protocol import LSPAny
from LSP.plugin.core.typing import NotRequired, StrEnum
from LSP.plugin.core.typing import cast
from typing import Callable, Tuple, TypedDict
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
        self.preview_task_id = 0

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
        if not TARBALL_NAME:
            return False
        try:
            with open(os.path.join(cls.basedir(), 'VERSION'), 'r') as file:
                return file.read().strip() != VERSION
        except OSError:
            return True

    @classmethod
    def install_or_update(cls) -> None:
        assert TARBALL_NAME
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
            if self.preview_task_id > 0:
                command: ExecuteCommandParams = {
                    'command': 'tinymist.doKillPreview',
                    'arguments': [f'$ublime-{self.preview_task_id}']
                }
                session.execute_command(command, False)
            self.preview_task_id += 1
            command: ExecuteCommandParams = {
                # 'command': 'tinymist.startDefaultPreview',
                'command': 'tinymist.doStartBrowsingPreview',
                # 'command': 'tinymist.doStartPreview',
                'arguments': [['--task-id', f'$ublime-{self.preview_task_id}'] + session.config.settings.get('preview.browsing.args')]
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

    def m_tinymist_compileStatus(self, params: CompileStatusParams) -> None:
        session = self.weaksession()
        if not session:
            return
        status = params['status']
        if status == CompileStatus.COMPILING:
            return  # Don't update the status message to prevent flickering from volatile page count report
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
        command_name = {
            'pdf': 'tinymist.exportPdf',
            'png': 'tinymist.exportPng',
            'svg': 'tinymist.exportSvg',
            'html': 'tinymist.exportHtml',
            'markdown': 'tinymist.exportMarkdown',
            'latex': 'tinymist.exportTeX'
        }.get(format)
        if not command_name:
            self._status_message(f'Unsupported format {format}')
            return
        if format in ('png', 'svg'):
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
        return [
            sublime.ListInputItem('Export as PDF', 'pdf'),
            sublime.ListInputItem('Export as PNG (by merging pages)', 'png'),
            sublime.ListInputItem('Export as SVG (by merging pages)', 'svg'),
            sublime.ListInputItem('Export as HTML', 'html'),
            sublime.ListInputItem('Export as Markdown', 'markdown'),
            sublime.ListInputItem('Export as LaTeX', 'latex')
        ]
