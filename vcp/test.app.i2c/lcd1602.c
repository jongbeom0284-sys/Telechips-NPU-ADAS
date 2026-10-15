#include <i2c.h>
#include <lcd.h>
#include "lcd1602.h"

void LCD1602_Run(void)
{
    SAL_OsInitFuncs();

    I2C_Init(); // I2C 초기화
    if (I2C_Open(I2C_CH, I2C_PORT, I2C_SPEED, NULL, NULL) != SAL_RET_SUCCESS) {
        mcu_printf("I2C open failed\n");
        return; //오픈 실패 시 진행하지 않고 fail 로그
    }

    uint32 detected_addr = I2C_ScanSlave(I2C_CH); //스캔
    mcu_printf("Detected I2C Slave Address: 0x%02X\n", detected_addr);

    lcd_init();    // LCD 초기화
    lcd_cmd(0x80); // 커서를 맨 앞으로
    lcd_print("Hello TOPST");

    while (1) {
        SAL_TaskSleep(1000);
    }
}
