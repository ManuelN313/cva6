# Imagen base: Ubuntu 24.04
FROM ubuntu:24.04

# Establecer el entorno no interactivo
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependencias necesarias
RUN apt-get update && apt-get install -y build-essential scons python3-dev git pre-commit zlib1g zlib1g-dev \
    libprotobuf-dev protobuf-compiler libprotoc-dev libgoogle-perftools-dev \
    libboost-all-dev  libhdf5-serial-dev python3-pydot python3-venv python3-tk mypy \
    m4 libcapstone-dev libpng-dev libelf-dev pkg-config wget cmake doxygen clang-format gcc-riscv64-linux-gnu \
    g++-riscv64-linux-gnu binutils-riscv64-linux-gnu && apt-get clean && rm -rf /var/lib/apt/lists/*

# Clonar el repositorio de gem5
RUN git clone https://github.com/gem5/gem5.git

# Establecer el directorio de trabajo
WORKDIR /gem5

# Compilar gem5 (una vez creado el contenedor)
# scons build/RISCV/gem5.opt -j$(nproc)