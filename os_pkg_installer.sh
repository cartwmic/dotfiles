#!/bin/sh

if [ "$2" = 'sdkman' ]; then # install via install script regardless of os
	if [ "$2" = 'sdkman' ]; then
		sudo curl -s "https://get.sdkman.io" | sudo zsh
	fi
elif [ "$1" = 'macos' ]; then
	brew install "$2"
elif [ "$1" = 'ubuntu' ]; then
	if [ "$2" = 'go-task' ] || [ "$2" = 'lazygit' ] || [ "$2" = 'starship' ] || [ "$2" = 'zellij' ]; then # install via install script
		if [ "$2" = 'go-task' ]; then
			sudo sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d
		elif [ "$2" = 'lazygit' ]; then
			cd $HOME || exit
			mkdir "lazygit"
			LAZYGIT_VERSION=$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" | grep -Po '"tag_name": "v\K[^"]*')
			curl -Lo "lazygit.tar.gz" "https://github.com/jesseduffield/lazygit/releases/latest/download/lazygit_${LAZYGIT_VERSION}_Linux_x86_64.tar.gz"
			tar xf "lazygit.tar.gz" "lazygit"
			sudo install "lazygit" /usr/local/bin
		elif [ "$2" = 'starship' ]; then
			curl -sS https://starship.rs/install.sh | sudo sh
		elif [ "$2" = 'zellij' ]; then
			cargo install --locked zellij
		fi
	elif [ "$2" = 'kitty' ]; then # don't install
		exit 0
	else # install via apt
		if [ "$2" = 'kubectl' ]; then
			sudo apt-get update
			sudo apt-get install -y apt-transport-https ca-certificates curl
			curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
			echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
			sudo apt-get update
		fi
		sudo apt install -y "$2"
	fi
else
	echo "os: '$1' is not supported"
	exit 1
fi
