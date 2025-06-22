#!/bin/sh

sh -c "$(curl -fsLS get.chezmoi.io)"

sudo cp bin/chezmoi /usr/bin/

chezmoi init --apply https://github.com/cartwmic/dotfiles.git
