.data
    N:      .dword 4096          # Tamaño de los vectores
    Alpha:  .dword 2             # Escalar a multiplicar

.bss
    .align 3
    X: .zero 32768               # Vector X (4096)*8 bytes
    Y: .zero 32768               # Vector Y (4096)*8 bytes
    Z: .zero 32768               # Vector Z (4096)*8 bytes

.text
.globl main
main:
    la t0, N
    ld t1, 0(t0)            
    la t2, Alpha
    ld t3, 0(t2)            
    fcvt.d.l f10, t3        

    la s2, X
    la s3, Y
    la s4, Z

    mv s5, s2               
    mv s6, s3               
    mv s7, s4               

    li t4, 0
    srai t5, t1, 3          

loop:
    beq t4, t5, end

    fld f0, 0(s5)
    fld f1, 0(s6)
    fmul.d f2, f10, f0
    fadd.d f3, f2, f1
    fsd f3, 0(s7)

    fld f4, 8(s5)
    fld f5, 8(s6)
    fmul.d f6, f10, f4
    fadd.d f7, f6, f5
    fsd f7, 8(s7)

    fld f8, 16(s5)
    fld f9, 16(s6)
    fmul.d f11, f10, f8
    fadd.d f12, f11, f9
    fsd f12, 16(s7)

    fld f13, 24(s5)
    fld f14, 24(s6)
    fmul.d f15, f10, f13
    fadd.d f16, f15, f14
    fsd f16, 24(s7)

    fld f17, 32(s5)
    fld f18, 32(s6)
    fmul.d f19, f10, f17
    fadd.d f20, f19, f18
    fsd f20, 32(s7)

    fld f21, 40(s5)
    fld f22, 40(s6)
    fmul.d f23, f10, f21
    fadd.d f24, f23, f22
    fsd f24, 40(s7)

    fld f25, 48(s5)
    fld f26, 48(s6)
    fmul.d f27, f10, f25
    fadd.d f28, f27, f26
    fsd f28, 48(s7)

    fld f29, 56(s5)
    fld f30, 56(s6)
    fmul.d f31, f10, f29
    fadd.d f0, f31, f30
    fsd f0, 56(s7)

    addi s5, s5, 64
    addi s6, s6, 64
    addi s7, s7, 64
    addi t4, t4, 1
    j loop

end:
    li a0, 0x0
    jal exit