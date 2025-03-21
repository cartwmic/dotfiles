#!/bin/sh

ret=0
if [ "$1" = 'true' ]; then
  echo "Skip fonts flag set to true, exit 0..."
elif [ "$2" = 'macos' ]; then
  echo "macos OS selected"
  brew install --cask font-sauce-code-pro-nerd-font
  ret=$?
elif [ "$2" = 'ubuntu' ]; then
  echo "ubuntu OS selected"
  cd /tmp || exit
  curl -L -o SourceCodePro.zip https://github.com/ryanoasis/nerd-fonts/releases/download/v3.3.0/SourceCodePro.zip
  unzip SourceCodePro.zip
  if [ ! -d "$HOME/.local/share/fonts" ]; then
    mkdir "$HOME/.local/share/fonts"
  fi
  mv ./*ttf "$HOME/.local/share/fonts"
  fc-cache -fv
  cd - || exit
  ret=$?
else
  echo "os: '$2' is not supported"
fi

printf "\xf0\x9f\x90\x8d\n"
printf "\xee\x82\xa0\n"

exit "$ret"
