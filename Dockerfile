############################################################
# Dockerfile to build Meeting Manager App
############################################################
#sudo docker build -t meeting-manager .
#sudo docker run -p 10031:10031 -i -t meeting-manager
###########################################################################

FROM ubuntu:22.04

# Set the default directory where CMD will execute
RUN mkdir /app
WORKDIR /app

# Copy the application folder inside the container
ADD . .

RUN apt-get update
ENV DEBIAN_FRONTEND=noninteractive

RUN apt update -y && apt upgrade -y && \
    apt-get install -y wget build-essential checkinstall  libreadline-dev  libncursesw5-dev  libssl-dev  libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev libffi-dev zlib1g-dev && \
    cd /usr/src && \
    wget https://www.python.org/ftp/python/3.8.1/Python-3.8.1.tgz && \
    tar xzf Python-3.8.1.tgz && \
    cd Python-3.8.1 && \
    ./configure --enable-optimizations && \
    make install
RUN apt-get install -y python3-pip

# Get pip to download and install requirements:
RUN pip3 install playwright
RUN playwright install
RUN playwright install-deps

RUN pip3 install python-dotenv
RUN pip3 install pymongo==3.10.1
RUN pip3 install pymongo[srv] 
RUN pip3 install tornado==4.5.2
RUN pip3 install requests
RUN pip3 install requests-toolbelt
RUN pip3 install wxcadm
RUN pip3 install cachetools

#Copy environment variables file. Overwrite it with prod.env if prod.env exists.
COPY .env prod.env* .env

# Set the default command to execute
# when creating a new container
CMD ["python3","-u","server.py"]
