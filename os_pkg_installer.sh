#!/bin/sh

if [ "$1" = 'macos' ]; then
	if [ "$2" = 'sdkman' ]; then
		brew tap sdkman/tap
		brew isntall sdkman-cli
	else
		brew install "$2"
	fi
fi
