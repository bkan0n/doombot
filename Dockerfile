FROM python:3.11

WORKDIR /usr/src/app

# For safety reason, create an user with lower privileges than root and run from there
RUN useradd -m -d /home/doom -s /bin/bash doom && \
    mkdir /usr/src/doom && \
    chown -R doom /usr/src/app

USER doom

COPY requirements.txt ./
RUN pip3 install --no-warn-script-location --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python3", "main.py", "-O"]