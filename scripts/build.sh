docker buildx build --platform=linux/amd64,linux/arm64 -t viyh/whisper:0.2.0-alpha.$(date +%s) -t viyh/whisper:0.2.0-alpha . --push
