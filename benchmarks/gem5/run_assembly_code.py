import sys
import os
import subprocess
import re

# ==============================================================================
# CONFIGURACION GLOBAL
# ==============================================================================
GEM5_ROOT = os.getcwd()
GCC_CMD = "riscv64-linux-gnu-gcc"
GEM5_BIN = "./build/RISCV/gem5.opt"
M5_INCLUDE = os.path.join(GEM5_ROOT, "include")
M5_OP_ASM = os.path.join(GEM5_ROOT, "util/m5/src/abi/riscv/m5op.S")

# ==============================================================================
# CONSTANTES DE OVERHEAD (Configuracion Nueva)
# ==============================================================================
OVERHEAD_CONSTANTS = {
    "numCycles":        37,
    "numInsts":         5,
    "icache_miss":      0,
    "dcache_miss":      0,
    "icache_access":    11,
    "dcache_access":    0,
    "branch_pred":      0,  
    "branch_miss":      0,  
    "simSeconds":       0.0 # En segundos
}

# ==============================================================================
# MAPA DE METRICAS
# ==============================================================================
METRICS_MAP = {
    "numCycles":        r"cores\.core\.numCycles",
    "numInsts":         r"board\.processor\.cores\.core\.commitStats0\.numInsts\s",
    "icache_miss":      r"l1icaches\.overallMisses::total",
    "dcache_miss":      r"l1dcaches\.overallMisses::total",
    "icache_access":    r"l1icaches\.overallAccesses::total",
    "dcache_access":    r"l1dcaches\.overallAccesses::total",
    "bp_look_d_cond":   r"branchPred\.btb\.lookups::DirectCond",
    "bp_look_d_uncond": r"branchPred\.btb\.lookups::DirectUncond",
    "bp_look_i_uncond": r"branchPred\.btb\.lookups::IndirectUncond",
    "btb_misp_d_cond":   r"branchPred\.btb\.mispredict::DirectCond",
    "btb_misp_i_uncond": r"branchPred\.btb\.mispredict::IndirectUncond",
    "simSeconds":       r"simSeconds",
    "ipc":              r"cores\.core\.ipc"
}

PRETTY_NAMES = {
    "numCycles": "Ciclos",
    "numInsts": "Instrucciones",
    "icache_miss": "Misses I-Cache",
    "dcache_miss": "Misses D-Cache",
    "icache_access": "Accesos I-Cache",
    "dcache_access": "Accesos D-Cache",
    "branch_pred": "Total Branch", 
    "branch_miss": "Branch Mispredicts",
    "simSeconds": "Tiempo (us)",
    "ipc": "IPC"
}

def compile_asm(asm_file):
    base_name = os.path.splitext(asm_file)[0]
    bin_file = base_name 

    print(f"[1/3] Compilando {asm_file} -> {bin_file}")
    cmd = [
        GCC_CMD, "-static", "-nostdlib",
        f"-I{M5_INCLUDE}", asm_file, M5_OP_ASM, "-o", bin_file
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ERROR DE COMPILACIÓN:\n", result.stderr)
        sys.exit(1)
    return bin_file

def run_gem5(config_file, bin_file):
    out_dir = "resultados"
    print(f"[2/3] Corriendo simulacion gem5 usando '{config_file}' (Output en {out_dir})...")
    
    # Limpiar stats anteriores para evitar confusion
    stats_path = os.path.join(out_dir, "stats.txt")
    if os.path.exists(stats_path):
        os.remove(stats_path)
        
    cmd = [GEM5_BIN, "-d", out_dir, config_file, bin_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ERROR EN GEM5:\n", result.stderr)
        sys.exit(1)
    return stats_path

def parse_stats(stats_path):
    print("[3/3] Analizando estadisticas")
    results = {key: 0.0 for key in METRICS_MAP} 
    
    block_count = 0
    in_target_block = False
    
    try:
        with open(stats_path, 'r') as f:
            for line in f:
                if "Begin Simulation Statistics" in line:
                    block_count += 1
                    # Asumimos que el ROI está en el primer bloque de stats
                    if block_count == 1:
                        in_target_block = True
                    else:
                        in_target_block = False
                        
                if in_target_block:
                    for key, regex in METRICS_MAP.items():
                        if re.search(regex, line):
                            parts = line.split()
                            if len(parts) >= 2:
                                try:
                                    val = float(parts[1])
                                    results[key] = val
                                except ValueError:
                                    pass
    except FileNotFoundError:
        print("Error: No se encontró stats.txt")
        sys.exit(1)

    # Total Saltos Logicos
    total_branches = (results.get("bp_look_d_cond", 0) + 
                      results.get("bp_look_d_uncond", 0) + 
                      results.get("bp_look_i_uncond", 0))
    results["branch_pred"] = total_branches

    # Total Mispredicts Logicos
    total_failures = (
        results.get("btb_misp_d_cond", 0) + 
        results.get("btb_misp_i_uncond", 0)
    )
    results["branch_miss"] = total_failures
    
    return results

def print_table(results):
    print("\n" + "="*65)
    print(f"{'MÉTRICA':<25} | {'OFICIAL':>15} | {'NETO':>15}")
    print("="*65)
    
    keys_order = ["numCycles", "numInsts", 
                  "icache_miss", "dcache_miss",
                  "icache_access", "dcache_access",
                  "branch_pred", "branch_miss", "simSeconds", "ipc"]
    
    clean_array_official = []
    clean_array_corrected = []
    
    # Pre-calculo para IPC corregido
    raw_insts = results.get("numInsts", 0)
    ovh_insts = OVERHEAD_CONSTANTS.get("numInsts", 0)
    net_insts = max(0, raw_insts - ovh_insts)
    
    raw_cycles = results.get("numCycles", 1) # Evitar div por cero
    ovh_cycles = OVERHEAD_CONSTANTS.get("numCycles", 0)
    net_cycles = max(1, raw_cycles - ovh_cycles) # Evitar div por cero
    
    corrected_ipc = net_insts / net_cycles

    for key in keys_order:
        val_official = results.get(key, 0)
        label = PRETTY_NAMES.get(key, key)
        
        overhead = OVERHEAD_CONSTANTS.get(key, 0)
        
        if key == "ipc":
            val_corrected = corrected_ipc
        elif key == "simSeconds":
            val_corrected = max(0, val_official - overhead)
        else:
            val_corrected = max(0, val_official - overhead)

        if key == "simSeconds":
            val_off_us = val_official * 1_000_000
            val_cor_us = val_corrected * 1_000_000
            
            fmt_off = f"{val_off_us:.2f}"
            fmt_cor = f"{val_cor_us:.2f}"
            
            clean_array_official.append(round(val_off_us))
            clean_array_corrected.append(round(val_cor_us))
        
        elif key == "ipc":
            fmt_off = f"{val_official:.4f}"
            fmt_cor = f"{val_corrected:.4f}"
            
            clean_array_official.append(round(val_official, 4))
            clean_array_corrected.append(round(val_corrected, 4))
            
        else:
            fmt_off = f"{int(val_official)}"
            fmt_cor = f"{int(val_corrected)}"
            
            clean_array_official.append(int(val_official))
            clean_array_corrected.append(int(val_corrected))
            
        print(f"{label:<25} | {fmt_off:>15} | {fmt_cor:>15}")
    print("="*65 + "\n")

    print(f"Clean result (OFFICIAL):  {clean_array_official}")
    print(f"Clean result (CORRECTED): {clean_array_corrected}\n")
    
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 run_perf.py <config_gem5.py> <programs/tu_programa.S>")
        sys.exit(1)
    
    config_file = sys.argv[1]
    asm_file = sys.argv[2]
    
    # Validaciones basicas
    if not os.path.exists(config_file):
        print(f"Error: El archivo de configuracion '{config_file}' no existe.")
        sys.exit(1)

    if not os.path.exists(asm_file):
        print(f"Error: El archivo de programa '{asm_file}' no existe.")
        sys.exit(1)
        
    binary = compile_asm(asm_file)
    stats_file = run_gem5(config_file, binary)
    metrics = parse_stats(stats_file)
    print_table(metrics)