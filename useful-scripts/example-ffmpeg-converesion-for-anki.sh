#!/bin/sh

# Example probe command
# ffprobe -show_format -print_format json "yandexpremium-78a81124-6f846a15-d968e55c-192675c2-6822e6e6.mp3"

OUTPUT_DIR="ffmpeg-output"
DIR="$HOME/Library/Application Support/Anki2/User 1/collection.media"
cd "$DIR" || exit
rm -rf "$OUTPUT_DIR"
mkdir ffmpeg-output
for f in *.mp3; do
	format=$(ffprobe -loglevel quiet -show_format -print_format json "$f" | jq .format.format_name)
	if [ "$format" = "\"ogg\"" ]; then
		echo "---FOUND ogg FORMATTED FILE---"
		echo "---FORMATTING FILE TO mp3---"
		ffmpeg -f ogg -i "$f" "$OUTPUT_DIR/$f"
		echo "---FORMATTING TO mp3 COMPLETE---"
	else
		echo "---FOUND $format FORMATTED FILE---"
	fi
done

cd - || exit
