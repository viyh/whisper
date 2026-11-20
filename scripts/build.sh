VERSION=0.5.2
docker buildx build --pull --platform=linux/amd64,linux/arm64 -t viyh/whisper:${VERSION}.$(date +%s) -t viyh/whisper:${VERSION} -t viyh/whisper:latest . --push
