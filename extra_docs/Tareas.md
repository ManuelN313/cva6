# Tareas pendientes

- Cambiar los accesos de D cache por los stalls del micro
- Revisar todos los parametros de gem5 con el comentario "# Revisar":
  - Hacer un microbenchmark con instrucciones comprimidas y verificar el parámetro decodeInputWidth y decodeCycleInput, comparar que pasa cuando deshabilitamos las instrucciones comprimidas.
  - Revisar la definicion de los parametros de las Caches y completar los de la Functional Units.
  - Verificar que es el LSQ y analizar esos parámetros. Probar con el benchmark de todos loads/store y compara la cantidad de accesos de memoria con la cantidad de ciclos respecto a verilator. Si la cantidad de acceso a memoria es correcta y la cantidad de ciclos tambien, nos quedamos tranquilo que estos parametros funcionan.
- Correr nuevamente el Daxpy y ver que las metricas tienen sentido respecto a la tablita. Si con el daxpy anda bien, hacer mas pruebas: multiplicación de matrices y predictor de salto.
- Redactar el analisis del gtwkwave con el programa chiquito.
- Avanzar con el programa para sacar la metrica de D cache en Verilator.

# Ver porque el mini programa de C no anda.


