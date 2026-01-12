#include <stdio.h>
#include <gem5/m5ops.h>

int main(void)
{
    m5_reset_stats(0, 0);

    // Code

    m5_dump_stats(0, 0); 

    m5_exit(0);
}