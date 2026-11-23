FROM traefik@sha256:a6c0194dda77bcb804824580f36fa7edc56e315b1acfe933366c8b52844a78a4

RUN apk add --no-cache tzdata

RUN mkdir -p /etc/traefik/dynamic

COPY dynamic/ /etc/traefik/dynamic/
