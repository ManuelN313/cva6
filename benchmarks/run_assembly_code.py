#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
import datetime
import re
import shlex
import shutil

# Configuracion
METRICS_MAP = {
    'x18': 'Ciclos (Cycles)',      # s2
    'x19': 'Instrucciones (Instr)',# s3
    'x20': 'I-Cache Miss',         # s4
    'x21': 'D-Cache Miss',         # s5
    'x22': 'I-Cache Access',       # s6
    'x23': 'D-Cache Access',       # s7
    'x24': 'Branches',             # s8
    'x25': 'Branch Miss',          # s9
    'x26': 'Tiempo (us)'           # s10
}

ORDERED_KEYS = ['x18', 'x19', 'x20', 'x21', 'x22', 'x23', 'x24', 'x25', 'x26']

def main():
    # Configuración de Directorios
    cva6_root = "/cva6"
    sim_dir = os.path.join(cva6_root, "verif/sim")
    setup_script = os.path.join(sim_dir, "setup-env.sh")
    
    # Definimos la carpeta de compilación a borrar
    work_ver_path = os.path.join(cva6_root, "work-ver")

    # Forzar Recompilacion
    # Borramos 'work-ver' para obligar a que se regenere el hardware con la nueva config.
    if os.path.exists(work_ver_path):
        try:
            shutil.rmtree(work_ver_path)
        except OSError as e:
            print(f"[!] Error eliminando work-ver: {e}")

    # Parsear Argumentos
    parser = argparse.ArgumentParser(description="Ejecutar simulación CVA6 y extraer métricas.")
    parser.add_argument("target", help="Target de la arquitectura (ej: cv64a6_imafdc_sv39)")
    parser.add_argument("asm_file", help="Ruta al archivo .S o .asm (relativa o absoluta)")
    args = parser.parse_args()

    # Validar existencia del archivo ASM
    abs_asm_path = os.path.abspath(args.asm_file)
    if not os.path.exists(abs_asm_path):
        print(f"Error: El archivo {abs_asm_path} no existe.")
        sys.exit(1)

    rel_asm_path = os.path.relpath(abs_asm_path, sim_dir)
    test_name = os.path.splitext(os.path.basename(abs_asm_path))[0]
    
    # Preparar Entorno
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1" 
    env["DV_SIMULATORS"] = "veri-testharness"

    # # Limpieza de los Logs
    today = datetime.date.today().strftime("%Y-%m-%d")
    log_dir_prediction = os.path.join(sim_dir, f"out_{today}", "veri-testharness_sim")

    log_main = f"{test_name}.{args.target}.log"
    log_iss  = f"{test_name}.{args.target}.log.iss"
    
    files_to_clean = [log_main, log_iss]

    for fname in files_to_clean:
        fpath = os.path.join(log_dir_prediction, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass

    # Construir Comando
    py_cmd_list = [
        "python3", "cva6.py",
        "--target", args.target,
        f"--iss={env['DV_SIMULATORS']}",
        "--iss_yaml=cva6.yaml",
        "--asm_tests", rel_asm_path,
        "--linker=../../config/gen_from_riscv_config/linker/link.ld",
        f"--gcc_opts=-static -mcmodel=medany -fvisibility=hidden -nostdlib -nostartfiles -g ../tests/custom/common/syscalls.c ../tests/custom/common/crt.S -lgcc -I../tests/custom/env -I../tests/custom/common"
    ]

    py_cmd_str = shlex.join(py_cmd_list)
    final_shell_cmd = f"source {setup_script} && {py_cmd_str}"
    
    try:
        subprocess.run(
            final_shell_cmd, 
            cwd=sim_dir, 
            check=True, 
            env=env, 
            stdout=subprocess.DEVNULL,
            shell=True,
            executable='/bin/bash'
        )
    except subprocess.CalledProcessError as e:
        print(f"\n[!] Error en simulación. Código: {e.returncode}")
        sys.exit(1)

    # Buscar Log
    log_path = os.path.join(log_dir_prediction, log_main)

    if not os.path.exists(log_path):
        print(f"[!] Log no encontrado: {log_path}")
        sys.exit(1)

    # Parsear Log
    final_values = {}
    try:
        with open(log_path, 'r') as f:
            for line in f:
                match = re.search(r'x\s*(\d+)\s+(0x[0-9a-fA-F]+)', line)
                if match:
                    reg_key = f"x{match.group(1)}"
                    if reg_key in METRICS_MAP:
                        final_values[reg_key] = int(match.group(2), 16)
    except Exception as e:
        print(f"[!] Error leyendo log: {e}")
        sys.exit(1)

    # Imprimir Resultados
    print("\n" + "="*55)
    print(f"RESULTADOS DE PERFORMANCE: {test_name}")
    print(f"TARGET: {args.target}")
    print("="*55)
    print(f"{'METRICA':<25} | {'REGISTRO':<10} | {'DECIMAL':<15}")
    print("-" * 55)

    clean_values_list = []

    for key in ORDERED_KEYS:
        val_dec = final_values.get(key, 0)
        metric_name = METRICS_MAP[key]
        
        clean_values_list.append(val_dec)
        print(f"{metric_name:<25} | {key:<10} | {val_dec}")
    
    print("-" * 55)

    # IPC
    ipc = 0.0
    if 'x18' in final_values and 'x19' in final_values:
        cycles = final_values['x18']
        instr = final_values['x19']
        if cycles > 0:
            ipc = instr / cycles
    
    print(f"{'IPC Calculado':<25} | {'N/A':<10} | {ipc:.4f}")
    
    clean_values_list.append(round(ipc, 4))

    print("="*55)
    
    # Clean Result
    print(f"\nclean result: {clean_values_list}\n")

if __name__ == "__main__":
    main()