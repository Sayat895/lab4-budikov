FROM python:3.12-slim

RUN apt-get update -o Acquire::ForceIPv4=true && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libegl1 \
    libfontconfig1 \
    libdbus-1-3 \
    libx11-xcb1 \
    libxcb-render0 \
    libxcb-shm0 \
    libxkbcommon-x11-0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-xinerama0 \
    libxcb-xfixes0 \
    libxcb-shape0 \
    libxcb-cursor0 \
    libxcb-xkb1 \
    xvfb \
    x11vnc \
    supervisor \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -c "import io,pathlib,tarfile,urllib.request; url='https://github.com/novnc/noVNC/archive/refs/tags/v1.6.0.tar.gz'; archive=tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(url, timeout=60).read()), mode='r:gz'); prefix='noVNC-1.6.0/'; root=pathlib.Path('/usr/share/novnc'); root.mkdir(parents=True, exist_ok=True); members=[m for m in archive.getmembers() if m.isfile() and m.name.startswith(prefix)]; [(root.joinpath(m.name[len(prefix):]).parent.mkdir(parents=True, exist_ok=True), root.joinpath(m.name[len(prefix):]).write_bytes(archive.extractfile(m).read())) for m in members]"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /tmp/runtime-root && chmod 700 /tmp/runtime-root
ENV XDG_RUNTIME_DIR=/tmp/runtime-root

COPY supervisord.conf /etc/supervisor/conf.d/desktop.conf
COPY . .

EXPOSE 6080

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/desktop.conf"]