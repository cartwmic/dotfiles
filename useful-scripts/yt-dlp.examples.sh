#! /bin/sh

failed=0
total="$#"
succeeded=0

echo "[$0 INFO] downloading $total files"
for var in "$@"; do
	echo "[$0 INFO] downloading $succeeded/$total $var"
	if ! yt-dlp --no-ignore-errors --download-archive archive.txt "$var"; then
		echo "[$0 INFO] $succeeded/$total $var failed to download"
		echo "$var" >>yt-dlp.errors.txt
		failed=$((failed + 1))
	else
		echo "[$0 INFO] $succeeded/$total $var download succeeded"
		succeeded=$((succeeded + 1))
	fi
done
echo "[$0 INFO] finished downloading files"
echo "[$0 INFO] $failed failed to download"
echo "[$0 INFO] $succeeded succeeded to download"
