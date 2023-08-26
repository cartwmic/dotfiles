#!/bin/sh

# install zsh for shell and python for dotdrop
sudo apt install zsh python3-pip unzip zip -y

# make zsh the default shell
sudo chsh -s "$(which zsh)" "$(whoami)"

# setup dotdrop
cd dotdrop || exit
pip3 install .
cd - || exit
