VERSION=0.2.1
docker buildx build --pull --platform=linux/amd64,linux/arm64 -t viyh/whisper:${VERSION}.$(date +%s) -t viyh/whisper:${VERSION} -t viyh/whisper:latest . --push
