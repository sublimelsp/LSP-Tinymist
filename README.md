# LSP-Tinymist

[![License](https://img.shields.io/github/license/sublimelsp/LSP-Tinymist)](https://github.com/sublimelsp/LSP-Tinymist/blob/master/LICENSE)

A plugin for the LSP client in Sublime Text with support for the [Tinymist](https://github.com/Myriad-Dreamin/tinymist)  language server for Typst.

## Installation

Install the [Typst](https://packages.sublimetext.io/packages/Typst/) package for syntax highlighting, and the [LSP](https://packages.sublimetext.io/packages/LSP/) and LSP-Tinymist packages from Package Control.
The language server executable is downloaded automatically when you open a Typst file and it is updated with new releases of this package.

## Configuration

Some configuration options are available in the package settings which can be opened using the *Preferences: LSP-Tinymist Settings* command from the command palette.

> [!TIP]
> To improve auto-completions in math mode, add the scope `text.typst markup.math` to the global `"auto_complete_selector"` setting (*Preferences: Settings* from the command palette) or in the syntax-specific settings (*Preferences: Settings - Syntax Specific*).

## Working with Multiple-Files Projects

Tinymist doesn't automatically know the main file of a multiple-files project.
You can explicitly pin the active Typst file as the main file using the command *LSP-Tinymist: Pin Main File* from the command palette.
