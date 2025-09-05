from __future__ import annotations
from .tarball import decompress, download
from LSP.plugin import AbstractPlugin
from LSP.plugin import register_plugin
from LSP.plugin import unregister_plugin
from LSP.plugin.core.protocol import ExecuteCommandParams
from typing import Callable, Tuple
import os
import sublime


PACKAGE_NAME = 'LSP-Tinymist'
VERSION = 'v0.13.24'
TARBALL_NAME = {
    'linux-arm64': 'tinymist-aarch64-unknown-linux-gnu.tar.gz',
    'linux-x64': 'tinymist-x86_64-unknown-linux-gnu.tar.gz',
    'osx-arm64': 'tinymist-aarch64-apple-darwin.tar.gz',
    'osx-x64': 'tinymist-x86_64-apple-darwin.tar.gz',
    'windows-arm64': 'tinymist-aarch64-pc-windows-msvc.zip',
    'windows-x64': 'tinymist-x86_64-pc-windows-msvc.zip',
}.get(f'{sublime.platform()}-{sublime.arch()}')


# class WordsCount(TypedDict):
#     chars: int
#     cjkChars: int
#     spaces: int
#     words: int


# class CompileStatusParams(TypedDict):
#     pageCount: int
#     path: str
#     status: str
#     wordsCount: WordsCount | None


def plugin_loaded() -> None:
    register_plugin(LspTinymistPlugin)


def plugin_unloaded() -> None:
    unregister_plugin(LspTinymistPlugin)


class LspTinymistPlugin(AbstractPlugin):

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

    def on_pre_server_command(self, command: ExecuteCommandParams, done_callback: Callable[[], None]) -> bool:
        # command_name = command['command']
        # if command_name == 'tinymist.runCodeLens':
        #     args = command.get('arguments')
        #     if isinstance(args, list) and len(args) > 0:
        #         action = args[0]
        #         if action == 'profile':
        #             sublime.set_timeout(done_callback)
        #             return True
        #         elif action == 'preview':
        #             sublime.set_timeout(done_callback)
        #             return True
        #         elif action == 'export-pdf':
        #             sublime.set_timeout(done_callback)
        #             return True
        #         elif action == 'more':
        #             sublime.set_timeout(done_callback)
        #             return True
        return False

    # def m_tinymist_compileStatus(self, params: CompileStatusParams) -> None:
    #     pass
