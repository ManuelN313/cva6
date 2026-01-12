import argparse

from gem5.components.boards.simple_board import SimpleBoard
from gem5.components.processors.base_cpu_core import BaseCPUCore
from gem5.components.processors.base_cpu_processor import BaseCPUProcessor
from gem5.components.memory.single_channel import SingleChannelDDR3_1600
from gem5.components.cachehierarchies.classic.private_l1_cache_hierarchy import (
    PrivateL1CacheHierarchy,
)
from gem5.isas import ISA
from gem5.simulate.simulator import Simulator
from gem5.resources.resource import BinaryResource

# Importamos objetos m5 nativos
from m5.objects import (
   RiscvMinorCPU,
   MinorFUPool,
   MinorDefaultIntFU,
   MinorDefaultIntMulFU,
   MinorDefaultIntDivFU,
   MinorDefaultFloatSimdFU,
   MinorDefaultMemFU,
   MinorDefaultMiscFU,
   MinorFU,
   MinorOpClassSet,
   MinorOpClass
)

# -------------------------------------------------------------------------
# Helper para definir clases de operaciones
# -------------------------------------------------------------------------
def make_op_class_set(op_classes_list):
    return MinorOpClassSet(
        opClasses=[MinorOpClass(opClass=name) for name in op_classes_list]
    )

# -------------------------------------------------------------------------
# Parsear Argumentos
# -------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Simulación CVA6 en gem5")
parser.add_argument("binary", type=str, help="Ruta al binario compilado (RISC-V ELF)")
args = parser.parse_args()

# -------------------------------------------------------------------------
# Definicion de las Unidades Funcionales 
# -------------------------------------------------------------------------
class CVA6FUPool(MinorFUPool):
    def __init__(self):
        super().__init__()

        # ALU: 1 ciclo
        alu_fu = MinorDefaultIntFU()
        alu_fu.opLat = 1
        
        # MULT: 2 ciclos
        mul_fu = MinorDefaultIntMulFU()
        mul_fu.opLat = 2
        
        # DIV: 64 ciclos
        div_fu = MinorDefaultIntDivFU()
        div_fu.opLat = 64
        div_fu.issueLat = 64
        
        # Floating Point y SIMD Estandar
        float_fu = MinorDefaultFloatSimdFU()
        
        # Memoria y Misc estandar
        mem_fu = MinorDefaultMemFU()
        misc_fu = MinorDefaultMiscFU()
        
        # Resto de Unidades
        my_units = [alu_fu, mul_fu, div_fu, float_fu, mem_fu, misc_fu]
        covered_ops = set()
        
        for unit in my_units:
            if hasattr(unit, 'opClasses') and unit.opClasses:
                for op_class in unit.opClasses.opClasses:
                    covered_ops.add(op_class.opClass)
        all_possible_ops = [op.opClass for op in MinorOpClassSet().opClasses]
        missing_ops = [op for op in all_possible_ops if op not in covered_ops]

        catch_all_fu = MinorFU(
            opClasses=make_op_class_set(missing_ops),
            opLat=6, 
            issueLat=1
        )
        
        self.funcUnits = [alu_fu, mul_fu, div_fu, float_fu, mem_fu, misc_fu, catch_all_fu]

# -------------------------------------------------------------------------
# Definicion del CPU CVA6
# -------------------------------------------------------------------------
class CVA6CPU(RiscvMinorCPU):
    def __init__(self):
        super().__init__()
        
        # Asignamos el pool de latencias personalizado
        self.executeFuncUnits = CVA6FUPool()

        # Configuración Single Issue (Correcta para CVA6)
        self.fetch1FetchLimit = 1
        self.fetch2InputBufferSize = 2 
        self.decodeInputBufferSize = 2
        self.executeInputWidth = 1
        self.executeIssueLimit = 1
        self.executeCommitLimit = 1
        self.executeMemoryIssueLimit = 1

# Wrapper para usarlo con la Standard Library de gem5
class CVA6Processor(BaseCPUProcessor):
    def __init__(self):
        core = BaseCPUCore(core=CVA6CPU(), isa=ISA.RISCV)
        super().__init__(cores=[core])

# -------------------------------------------------------------------------
# Configuracion de Caches
# -------------------------------------------------------------------------
class CVA6CacheHierarchy(PrivateL1CacheHierarchy):
    def __init__(self, l1d_size, l1i_size):
        super().__init__(l1d_size=l1d_size, l1i_size=l1i_size)

    def incorporate_cache(self, board):
        super().incorporate_cache(board)
        
        for i, core in enumerate(board.get_processor().get_cores()):
            
            # L1 Instruction Cache
            self.l1icaches[i].tag_latency = 1
            self.l1icaches[i].data_latency = 1
            self.l1icaches[i].response_latency = 1
            self.l1icaches[i].assoc = 4
            
            # L1 Data Cache
            self.l1dcaches[i].tag_latency = 3
            self.l1dcaches[i].data_latency = 3
            self.l1dcaches[i].response_latency = 3
            self.l1dcaches[i].assoc = 8

# -------------------------------------------------------------------------
# Script Principal
# -------------------------------------------------------------------------
binary = BinaryResource(args.binary)

processor = CVA6Processor()

cache_hierarchy = CVA6CacheHierarchy(
    l1d_size="32KiB",
    l1i_size="32KiB"
)

memory = SingleChannelDDR3_1600(size="1GiB")

board = SimpleBoard(
    clk_freq="50MHz",
    processor=processor,
    memory=memory,
    cache_hierarchy=cache_hierarchy
)

board.set_se_binary_workload(binary)

simulator = Simulator(board=board)
print("Iniciando simulacion del CVA6")
simulator.run()