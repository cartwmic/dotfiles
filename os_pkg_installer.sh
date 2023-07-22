#!/bin/sh

if [ "$2" = 'sdkman' ]; then
	curl -s "https://get.sdkman.io" | zsh
elif [ "$1" = 'macos' ]; then
	brew install "$2"
fi
