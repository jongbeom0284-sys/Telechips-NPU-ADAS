#include <stdint.h>
#include <gpio.h>
#include <pdm.h>
#include "pdm_led.h"

static void ConfigureLedPWM(uint32 channel, uint32 port, uint32 duty_ns)
{
    PDMModeConfig_t pwm_cfg;
    uint32 wait_cnt = 0;

    pwm_cfg.mcPortNumber      = port;  // 사용할 포트
    pwm_cfg.mcOperationMode   = PDM_OUTPUT_MODE_PHASE_1;  // 기본 단일 위상 출력 모드
    pwm_cfg.mcInversedSignal  = 0;  // 신호 반전 사용 안함
    pwm_cfg.mcOutSignalInIdle = 0;  // 유휴 상태 시 출력 없음
    pwm_cfg.mcLoopCount       = 0;  // 루프카운트(0:무한반복)
    pwm_cfg.mcOutputCtrl      = 0;  // 기본 출력 제어 설정
    pwm_cfg.mcPeriodNanoSec1  = 1000000;  // 주기 1ms(1kHz)
    pwm_cfg.mcDutyNanoSec1    = duty_ns;  // 듀티 설정 값
    pwm_cfg.mcPeriodNanoSec2  = 0;  // 사용 x
    pwm_cfg.mcDutyNanoSec2    = 0;  // 사용 x

    PDM_Disable(channel, PMM_ON);  // PDM 비활성화
    while (PDM_GetChannelStatus(channel))  // PDM 꺼질 때까지 대기
    {
        SAL_TaskSleep(1);
        if (++wait_cnt > 100)
        {
            mcu_printf("Timeout on channel %d\n", channel);
            return;
        }
	}

    if (PDM_SetConfig(channel, &pwm_cfg) != SAL_RET_SUCCESS)
	    {
            mcu_printf("SetConfig fail (CH:%d)\n", channel);
            return;
	    }

    if (PDM_Enable(channel, PMM_ON) != SAL_RET_SUCCESS)
	    {
            mcu_printf("Enable fail (CH:%d)\n", channel);
            return;
	    }
}

void PDM_Led_Run(void)
{
    PDM_Init();  // PDM 초기화
    ConfigureLedPWM(3, GPIO_PERICH_CH0, 0);  // 초기 상태: LED off

    while (1)
    {
        for (uint32 duty = 0; duty <= 1000000; duty += 10000)  // 밝기 증가 단계
        {
            ConfigureLedPWM(3, GPIO_PERICH_CH0, duty);  // 듀티 증가
            SAL_TaskSleep(5);
        }

        for (uint32 duty = 1000000; duty > 0; duty -= 10000)  // 밝기 감소 단계
        {
            ConfigureLedPWM(3, GPIO_PERICH_CH0, duty);  // 듀티 감소
            SAL_TaskSleep(5);
        }
    }
}
