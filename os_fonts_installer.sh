#!/bin/sh

ret=0
if [ "$1" = 'true' ]; then
	echo "Skip fonts flag set to true, exit 0..."
elif [ "$2" = 'macos' ]; then
	echo "macos OS selected"
	brew tap homebrew/cask-fonts && brew install --cask font-sauce-code-pro-nerd-font
	ret=$?
else
	echo "os: '$2' is not supported"
fi

printf "\xf0\x9f\x90\x8d\n"
printf "\xee\x82\xa0\n"

exit "$ret"
