#!/bin/bash

open_sem(){
    mkfifo pipe-$$
    exec 3<>pipe-$$
    rm pipe-$$
    local i=$1
    for((;i>0;i--)); do
        printf %s 000 >&3
    done
}

# run the given command asynchronously and pop/push tokens
run_with_lock(){
    local x
    # this read waits until there is something to read
    read -u 3 -n 3 x && ((0==x)) || exit $x
    (
     ( "$@"; )
    # push the return code of the command to the semaphore
    printf '%.3d' $? >&3
    )&
}

generate_mp4() {
  clip_length=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 -i $1.mp3)

  ffmpeg -y -loop 1 -framerate 10 -i $1.webp -i $1.mp3 -vf "scale=1280:720,setsar=1" -c:v libx264 -tune stillimage -b:v 200k -pix_fmt yuv420p -movflags +faststart -t $clip_length $1.mp4
}

path="$1"
files=$(find $path -type f -name '*.mp3' | sed "s/.mp3//")

N=4
open_sem $N
for file in $files
do
  echo $file
  echo "Generating mp4..."
  if [ -f "$file.mp4" ]; then
    echo "File exists. Skipping..."
  else
    run_with_lock generate_mp4 $file
  fi
done
