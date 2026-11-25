FROM traefik@sha256:00c9734983e74ae35a1fc18eaee9e9da13f3dde95c4e45b3b8c3b60e0dbd2d17

RUN apk add --no-cache tzdata

RUN mkdir -p /etc/traefik/dynamic

COPY dynamic/ /etc/traefik/dynamic/
