#!/bin/sh

if [ "$2" = 'sdkman' ]; then # install via install script regardless of os
	if [ "$2" = 'sdkman' ]; then
		curl -s "https://get.sdkman.io" | sudo -u cartwmic bash
	fi
elif [ "$1" = 'macos' ]; then
	brew install "$2"
elif [ "$1" = 'ubuntu' ]; then
	if [ "$2" = 'go-task' ] || [ "$2" = 'lazygit' ] || [ "$2" = 'starship' ] || [ "$2" = 'zellij' ] || [ "$2" = 'kustomize' ] || [ "$2" = 'kubeseal' ]; then # install via install script
		if [ "$2" = 'go-task' ]; then
			sudo -u cartwmic sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b "$HOME/.local/bin"
		elif [ "$2" = 'lazygit' ]; then
			cd "$HOME" || exit
			mkdir "lazygit"
			LAZYGIT_VERSION=$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" | grep -Po '"tag_name": "v\K[^"]*')
			curl -Lo "lazygit.tar.gz" "https://github.com/jesseduffield/lazygit/releases/latest/download/lazygit_${LAZYGIT_VERSION}_Linux_x86_64.tar.gz"
			tar xf "lazygit.tar.gz" "lazygit"
			sudo install "lazygit" /usr/local/bin
		elif [ "$2" = 'starship' ]; then
			curl -sS https://starship.rs/install.sh | sudo -u cartwmic sh
		elif [ "$2" = 'zellij' ]; then
			cargo install --locked zellij
		elif [ "$2" = 'kustomize' ]; then
			cd "$HOME/.local/bin" || exit
			curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
			cd - || exit
		elif [ "$2" = 'kubeseal' ]; then
			sudo apt install jq

			# Fetch the latest sealed-secrets version using GitHub API
			KUBESEAL_VERSION=$(curl -s https://api.github.com/repos/bitnami-labs/sealed-secrets/tags | jq -r '.[0].name' | cut -c 2-)

			# Check if the version was fetched successfully
			if [ -z "$KUBESEAL_VERSION" ]; then
				echo "Failed to fetch the latest KUBESEAL_VERSION"
				exit 1
			fi

			wget "https://github.com/bitnami-labs/sealed-secrets/releases/download/v${KUBESEAL_VERSION}/kubeseal-${KUBESEAL_VERSION}-linux-amd64.tar.gz"
			tar -xvzf "kubeseal-${KUBESEAL_VERSION}-linux-amd64.tar.gz" kubeseal
			sudo install -m 755 kubeseal /usr/local/bin/kubeseal
		fi
	else # install via apt
		if [ "$2" = 'kubectl' ]; then
			sudo apt-get update
			sudo apt-get install -y apt-transport-https ca-certificates curl
			curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
			echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
			sudo apt-get update
		elif [ "$2" = 'neovim' ]; then
			sudo apt-get install software-properties-common
			sudo add-apt-repository ppa:neovim-ppa/unstable
			sudo apt-get update
		elif [ "$2" = 'helm' ]; then
			curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg >/dev/null
			sudo apt-get install apt-transport-https --yes
			echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm-stable-debian.list
			sudo apt-get update
		fi
		sudo apt install -y "$2"
	fi
else
	echo "os: '$1' is not supported"
	exit 1
fi
