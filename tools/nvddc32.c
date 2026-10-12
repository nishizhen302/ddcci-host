/* nvddc32.exe —— 32 位 nvapi I2C helper：在英伟达显卡上收发任意 DDC/CI 帧。
 *
 * 为什么是 32 位独立进程：实机(英伟达 + Win7)上 64 位 nvapi64.dll 对任何 version /
 * 任何 handle 都回 -8 INVALID_HANDLE，是死路；只有 32 位 nvapi.dll 能通。控制台本体
 * 是 64 位 Python，故把 nvapi 调用隔离到这个 32 位 helper，父进程 subprocess 驱动。
 *
 * 2026-07-24 实机验证出来的配方（改一处就不通，别乱动）：
 *   - 32 位 nvapi.dll + NV_I2C_INFO_V1(version = sizeof|1<<16, 32 位下 = 0x00010020)
 *   - 非 Ex 的 NvAPI_I2CWrite/I2CRead (ID 0xE812EB07 / 0x2FDE12C5)
 *   - handle 参数不是 EnumNvidiaDisplayHandle 返回的 0xDE0000xx 句柄(那样恒 -8)。
 *     2026-07-24 抓包那台机上是 0x100，当时枚举到两块屏(0x100/0x400)，于是错记成
 *     "第一块 display 的 displayMask"。2026-07-30 只接一块屏(枚举只剩 0x400)时
 *     handle=0x400 恒 -8，整条通道看着像死了。现在改成开机探测(见 pick_handle)：
 *     逐个候选写一字节到 0xA0，返回码不是 -8 就是今天可用的 handle。
 *     排障看 `hscan`；`NVDDC32_HANDLE=<hex>` 或 serve 的 `h <hex>` 可强制指定。
 *   - 选哪块屏靠结构体里的 displayMask 字段(南微屏实机 = 0x400)
 *   - bIsDDCPort=1, regAddrSize=0 且 pbI2cRegAddress=NULL(DDC 源地址 0x51 并进 data,
 *     不作寄存器), i2cSpeed=0x0A, 写地址 0x5E / 读地址 0x5F
 *
 * 用法(一次性)：
 *   nvddc32 enum                                  枚举 displayMask -> "OK 0x.. 0x.."
 *   nvddc32 edid <mask>                           读 128B EDID -> "OK <hex>"
 *   nvddc32 w <mask> <addr> <b0 b1 ...>           原样写 addr(hex 字节, 已含校验)
 *   nvddc32 r <mask> <addr> <n>                   从 addr 读 n 字节 -> "OK <hex>"
 *   nvddc32 x <mask> <waddr> <raddr> <n> <ms> <b0 ...>   写+延时+读, 一次往返
 *   nvddc32 serve [ppid]                          常驻: 逐行收上面的命令, 逐行回结果
 *                                                 带 ppid 则父进程一退本进程就自杀
 *   nvddc32 list                                  枚举+EDID 明细(均匀度软件在用)
 *   nvddc32 set <0-100> [mask]                    南微亮度短帧 90 val chk
 *   nvddc32 raw <mask> <hex...>                   南微短帧, 自动补 xor 校验(调试)
 * 回应固定 "OK ..." / "ERR ..."；一次性模式退出码 0=成功。 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ID_Initialize   0x0150E828u
#define ID_Enum         0x9ABDD40Du
#define ID_GetOutputId  0xD995937Eu
#define ID_I2CWrite     0xE812EB07u
#define ID_I2CRead      0x2FDE12C5u

#define MAX_MASK   16
#define MAX_BYTES  128
#define NANWEI_ADDR 0x5E

#pragma pack(push, 8)
typedef struct {
    unsigned int   version, displayMask;
    unsigned char  bIsDDCPort, i2cDevAddress;
    unsigned char *pbI2cRegAddress;
    unsigned int   regAddrSize;
    unsigned char *pbData;
    unsigned int   cbSize, i2cSpeed;
} NV_I2C_V1;
#pragma pack(pop)

typedef void *(__cdecl *QI_FN)(unsigned int);   /* 32 位 nvapi 是 __cdecl, 不是 stdcall */
typedef int   (__cdecl *FN0)(void);
typedef int   (__cdecl *FN2)(void *, void *);
typedef int   (__cdecl *ENUM_FN)(unsigned int, void **);
typedef int   (__cdecl *OUT_FN)(void *, unsigned int *);

#define VER1 ((unsigned int)sizeof(NV_I2C_V1) | (1u << 16))
#define I2C_SPEED 0x0A

#define NVAPI_INVALID_HANDLE (-8)       /* handle 没过驱动校验层, 帧根本没发出去 */

static FN2 Write, Read;
static void *g_handle;                  /* I2CWrite/Read 的第一个参数, 探出来的 */
static int g_handle_probed;             /* 1 = 探针确认过, 0 = 只是回退到 masks[0] */
static unsigned int g_masks[MAX_MASK];
static void *g_raw[MAX_MASK];           /* Enum 返回的原始句柄 (0xDE0000xx) */
static int g_nmask;

static int i2c_write(unsigned int target, unsigned char addr,
                     const unsigned char *data, int n);
static void pick_handle(void);

static int nv_init(void)
{
    HINSTANCE nv = LoadLibraryW(L"nvapi.dll");
    if (!nv) { printf("ERR load nvapi.dll failed (no 32-bit NVIDIA driver?)\n"); return -100; }
    QI_FN qi = (QI_FN)GetProcAddress(nv, "nvapi_QueryInterface");
    if (!qi) { printf("ERR no nvapi_QueryInterface\n"); return -101; }
    FN0     Init   = (FN0)qi(ID_Initialize);
    ENUM_FN Enum   = (ENUM_FN)qi(ID_Enum);
    OUT_FN  GetOut = (OUT_FN)qi(ID_GetOutputId);
    Write = (FN2)qi(ID_I2CWrite);
    Read  = (FN2)qi(ID_I2CRead);
    if (!Init || !Enum || !Write || !Read) { printf("ERR nvapi interfaces incomplete\n"); return -102; }
    Init();
    for (int i = 0; i < MAX_MASK; i++) {
        void *h = NULL;
        if (Enum((unsigned)i, &h) != 0) break;   /* -7 = END_ENUMERATION */
        unsigned int m = 0;
        if (GetOut) GetOut(h, &m);
        g_raw[g_nmask] = h;
        g_masks[g_nmask++] = m;
    }
    if (g_nmask == 0) { printf("ERR no display enumerated\n"); return -103; }
    pick_handle();
    return 0;
}

/* 原样写 n 字节到 addr(数据里该带什么由调用方决定)。返回 nvapi st。 */
static int i2c_write(unsigned int target, unsigned char addr,
                     const unsigned char *data, int n)
{
    NV_I2C_V1 info;
    ZeroMemory(&info, sizeof(info));
    info.version = VER1;
    info.displayMask = target;
    info.bIsDDCPort = 1;
    info.i2cDevAddress = addr;
    info.regAddrSize = 0;                /* 0x51 并进 data, 不作寄存器 */
    info.pbData = (unsigned char *)data;
    info.cbSize = (unsigned int)n;
    info.i2cSpeed = I2C_SPEED;
    return Write(g_handle, &info);
}

/* 从 addr 读 n 字节(DDC 回读无寄存器阶段)。返回 nvapi st。 */
static int i2c_read(unsigned int target, unsigned char addr,
                    unsigned char *buf, int n)
{
    NV_I2C_V1 info;
    ZeroMemory(&info, sizeof(info));
    info.version = VER1;
    info.displayMask = target;
    info.bIsDDCPort = 1;
    info.i2cDevAddress = addr;
    info.regAddrSize = 0;
    info.pbData = buf;
    info.cbSize = (unsigned int)n;
    info.i2cSpeed = I2C_SPEED;
    return Read(g_handle, &info);
}

/* ---- handle 探测 ----------------------------------------------------------
 * I2CWrite/Read 的第一个参数不是 Enum 出来的句柄(那样恒 -8), 2026-07-24 抓包时
 * 那台机上是 0x100 —— 当时枚举到两块屏(0x100/0x400), 于是记成了"第一块屏的 mask"。
 * 2026-07-30 只接一块屏(枚举只剩 0x400)时这条规则就崩了: handle=0x400 恒 -8,
 * 连 EDID 都读不到, 上层看到的就是"整条通道死了"。
 *
 * 所以不猜: 逐个候选发一帧, 只看返回码。-8 = 驱动不认这个 handle; 其它任何码
 * (0 成功 / NAK 类错误) 都说明 handle 过了校验层, 帧真发出去了。写 EDID 地址
 * 0xA0 一个字节做探针 —— 无副作用, 不读回不 Sleep, 一次几百微秒, 全表扫完 <50ms。
 */

/* 候选表: 枚举到的 mask 优先(0x100 当年就这么来的), 再补全部单 bit 值(屏拔了以后
   0x100 不在枚举结果里, 但 handle 可能仍要它), 最后才是 Enum 的原始句柄。 */
static int handle_candidates(void **out, int max)
{
    int n = 0;
    for (int i = 0; i < g_nmask && n < max; i++)
        out[n++] = (void *)(UINT_PTR)g_masks[i];
    for (int k = 0; k < 32 && n < max; k++) {
        void *h = (void *)(UINT_PTR)(1u << k);
        int dup = 0;
        for (int j = 0; j < n; j++) if (out[j] == h) dup = 1;
        if (!dup) out[n++] = h;
    }
    for (int i = 0; i < g_nmask && n < max; i++)
        if (g_raw[i]) out[n++] = g_raw[i];
    return n;
}

static int handle_probe_st(void *h, unsigned int target)
{
    void *save = g_handle;
    unsigned char off = 0x00;
    int st;
    g_handle = h;
    st = i2c_write(target, 0xA0, &off, 1);
    g_handle = save;
    return st;
}

/* 选定 g_handle。NVDDC32_HANDLE 环境变量可强制指定(hex), 用于压过探测结果。 */
static void pick_handle(void)
{
    void *cand[MAX_MASK * 2 + 32];
    int nc, i;
    const char *env = getenv("NVDDC32_HANDLE");

    g_handle = (void *)(UINT_PTR)g_masks[0];   /* 探不到就维持老行为 */
    g_handle_probed = 0;
    if (env && *env) {
        g_handle = (void *)(UINT_PTR)strtoul(env, NULL, 16);
        g_handle_probed = 2;                   /* 2 = 人工指定 */
        return;
    }
    nc = handle_candidates(cand, (int)(sizeof(cand) / sizeof(cand[0])));
    for (i = 0; i < nc; i++) {
        if (handle_probe_st(cand[i], g_masks[0]) != NVAPI_INVALID_HANDLE) {
            g_handle = cand[i];
            g_handle_probed = 1;
            return;
        }
    }
}

/* 南微短帧(Beacon 抓包同款): payload 后自动追 xor 校验, 种子 = 0x5E。 */
static int write_nanwei_short(unsigned int target, const unsigned char *payload, int n)
{
    unsigned char buf[MAX_BYTES];
    unsigned char chk = NANWEI_ADDR;
    int i;
    for (i = 0; i < n && i < MAX_BYTES - 1; i++) { buf[i] = payload[i]; chk ^= payload[i]; }
    buf[i++] = chk;
    return i2c_write(target, NANWEI_ADDR, buf, i);
}

/* 读目标屏 128 字节 EDID: 写 0xA0 偏移 0, 再从 0xA1 读。返回读的 st。 */
static int read_edid(unsigned int target, unsigned char *edid)
{
    unsigned char off = 0x00;
    i2c_write(target, 0xA0, &off, 1);
    Sleep(40);
    return i2c_read(target, 0xA1, edid, 128);
}

static void edid_mfr(const unsigned char *e, char *out)
{
    unsigned int id = (e[8] << 8) | e[9];
    out[0] = (char)('A' + ((id >> 10) & 0x1F) - 1);
    out[1] = (char)('A' + ((id >> 5) & 0x1F) - 1);
    out[2] = (char)('A' + (id & 0x1F) - 1);
    out[3] = 0;
}

/* EDID 4 个 descriptor 里找 0xFC(显示器名)。找不到 out 置空。 */
static void edid_model(const unsigned char *e, char *out, int outsz)
{
    out[0] = 0;
    for (int d = 54; d <= 108; d += 18) {
        if (e[d] == 0 && e[d + 1] == 0 && e[d + 2] == 0 && e[d + 3] == 0xFC) {
            int k = 0;
            for (int j = 0; j < 13 && k < outsz - 1; j++) {
                unsigned char c = e[d + 5 + j];
                if (c == 0x0A || c == 0) break;
                out[k++] = (char)c;
            }
            out[k] = 0;
            return;
        }
    }
}

static void print_hex(const unsigned char *b, int n)
{
    for (int i = 0; i < n; i++) printf("%02X", b[i]);
    printf("\n");
}

/* 命令分发。argv[0] 是命令名(不含程序名)。返回 0=成功, 非 0=失败。
   serve 与一次性模式共用, 所有回应写 stdout 一行。 */
static int dispatch(int argc, char **argv)
{
    if (argc < 1) { printf("ERR empty\n"); return 2; }
    const char *cmd = argv[0];

    if (_stricmp(cmd, "enum") == 0) {
        printf("OK");
        for (int i = 0; i < g_nmask; i++) printf(" 0x%08X", g_masks[i]);
        printf("\n");
        return 0;
    }

    if (_stricmp(cmd, "edid") == 0 && argc >= 2) {
        unsigned int target = (unsigned int)strtoul(argv[1], NULL, 16);
        unsigned char e[128];
        ZeroMemory(e, sizeof(e));
        int st = read_edid(target, e);
        if (st != 0) { printf("ERR st=%d\n", st); return 1; }
        printf("OK ");
        print_hex(e, 128);
        return 0;
    }

    if (_stricmp(cmd, "w") == 0 && argc >= 4) {
        unsigned int target = (unsigned int)strtoul(argv[1], NULL, 16);
        unsigned char addr = (unsigned char)strtoul(argv[2], NULL, 16);
        unsigned char data[MAX_BYTES];
        int n = 0;
        for (int a = 3; a < argc && n < MAX_BYTES; a++)
            data[n++] = (unsigned char)strtoul(argv[a], NULL, 16);
        int st = i2c_write(target, addr, data, n);
        if (st != 0) { printf("ERR st=%d\n", st); return 1; }
        printf("OK\n");
        return 0;
    }

    if (_stricmp(cmd, "r") == 0 && argc >= 4) {
        unsigned int target = (unsigned int)strtoul(argv[1], NULL, 16);
        unsigned char addr = (unsigned char)strtoul(argv[2], NULL, 16);
        int n = atoi(argv[3]);
        if (n <= 0 || n > MAX_BYTES) { printf("ERR bad n\n"); return 2; }
        unsigned char buf[MAX_BYTES];
        ZeroMemory(buf, sizeof(buf));
        int st = i2c_read(target, addr, buf, n);
        if (st != 0) { printf("ERR st=%d\n", st); return 1; }
        printf("OK ");
        print_hex(buf, n);
        return 0;
    }

    /* x <mask> <waddr> <raddr> <n> <delayms> <b0...> —— 一次 IPC 完成写+读, GUI 用 */
    if (_stricmp(cmd, "x") == 0 && argc >= 7) {
        unsigned int target = (unsigned int)strtoul(argv[1], NULL, 16);
        unsigned char waddr = (unsigned char)strtoul(argv[2], NULL, 16);
        unsigned char raddr = (unsigned char)strtoul(argv[3], NULL, 16);
        int n = atoi(argv[4]);
        int ms = atoi(argv[5]);
        if (n <= 0 || n > MAX_BYTES) { printf("ERR bad n\n"); return 2; }
        unsigned char data[MAX_BYTES];
        int wn = 0;
        for (int a = 6; a < argc && wn < MAX_BYTES; a++)
            data[wn++] = (unsigned char)strtoul(argv[a], NULL, 16);
        int st = i2c_write(target, waddr, data, wn);
        if (st != 0) { printf("ERR wst=%d\n", st); return 1; }
        if (ms > 0) Sleep((DWORD)ms);
        unsigned char buf[MAX_BYTES];
        ZeroMemory(buf, sizeof(buf));
        st = i2c_read(target, raddr, buf, n);
        if (st != 0) { printf("ERR rst=%d\n", st); return 1; }
        printf("OK ");
        print_hex(buf, n);
        return 0;
    }

    /* handle 全表扫描: 每个候选发一帧看返回码。-8 = 驱动不认这个 handle。
       给"整条通道突然死了"排障用: 有任何一行 A0_st 不是 -8, 那行就是今天该用的
       handle; 全是 -8 才是驱动/显卡层面真的没了。 */
    if (_stricmp(cmd, "hscan") == 0) {
        unsigned int target = (argc >= 2) ? (unsigned int)strtoul(argv[1], NULL, 16)
                                          : g_masks[0];
        /* 长帧 GET VCP 亮度, 与控制台 _probe() 发的完全一致, 无副作用 */
        unsigned char getvcp[5] = { 0x51, 0x82, 0x01, 0x10, 0x9C };
        void *cand[MAX_MASK * 2 + 32];
        int nc = handle_candidates(cand, (int)(sizeof(cand) / sizeof(cand[0])));
        printf("hscan target=0x%X candidates=%d current=0x%X probed=%d\n",
               target, nc, (unsigned)(UINT_PTR)g_handle, g_handle_probed);
        for (int i = 0; i < nc; i++) {
            int a0 = handle_probe_st(cand[i], target);
            printf("h=0x%08X A0_st=%d", (unsigned)(UINT_PTR)cand[i], a0);
            if (a0 != NVAPI_INVALID_HANDLE) {
                void *save = g_handle;
                unsigned char e[128];
                int est, wst;
                g_handle = cand[i];
                wst = i2c_write(target, NANWEI_ADDR, getvcp, 5);
                ZeroMemory(e, sizeof(e));
                est = read_edid(target, e);
                g_handle = save;
                printf("  <== ACCEPTED  5E_long_st=%d  edid_st=%d edid_ok=%d",
                       wst, est, (est == 0 && e[0] == 0x00 && e[1] == 0xFF));
            }
            printf("\n");
        }
        return 0;
    }

    if (_stricmp(cmd, "h") == 0 && argc >= 2) {
        g_handle = (void *)(UINT_PTR)strtoul(argv[1], NULL, 16);
        g_handle_probed = 2;
        printf("OK handle=0x%X\n", (unsigned)(UINT_PTR)g_handle);
        return 0;
    }

    if (_stricmp(cmd, "list") == 0) {
        printf("handle=0x%X probed=%d displays=%d\n",
               (unsigned)(UINT_PTR)g_handle, g_handle_probed, g_nmask);
        for (int i = 0; i < g_nmask; i++) {
            unsigned char e[128];
            ZeroMemory(e, sizeof(e));
            int st = read_edid(g_masks[i], e);
            int ok = (st == 0 && e[0] == 0x00 && e[1] == 0xFF && e[2] == 0xFF);
            char mfr[8] = "???", model[32] = "";
            if (ok) { edid_mfr(e, mfr); edid_model(e, model, sizeof(model)); }
            printf("#%d mask=0x%08X edid=%d mfr=%s model=%s\n",
                   i, g_masks[i], ok, mfr, model[0] ? model : "(unknown)");
        }
        return 0;
    }

    if (_stricmp(cmd, "set") == 0 && argc >= 2) {
        int val = atoi(argv[1]);
        if (val < 0) val = 0;
        if (val > 100) val = 100;
        unsigned int target = (argc >= 3) ? (unsigned int)strtoul(argv[2], NULL, 16)
                                          : g_masks[0];
        unsigned char payload[2] = { 0x90, (unsigned char)val };
        int st = write_nanwei_short(target, payload, 2);
        printf("set bright=%d target=0x%X st=%d %s\n", val, target, st,
               st == 0 ? "OK" : "FAIL");
        return st == 0 ? 0 : 1;
    }

    if (_stricmp(cmd, "raw") == 0 && argc >= 3) {
        unsigned int target = (unsigned int)strtoul(argv[1], NULL, 16);
        unsigned char payload[32];
        int n = 0;
        for (int a = 2; a < argc && n < 32; a++)
            payload[n++] = (unsigned char)strtoul(argv[a], NULL, 16);
        int st = write_nanwei_short(target, payload, n);
        printf("raw target=0x%X n=%d st=%d %s\n", target, n, st,
               st == 0 ? "OK" : "FAIL");
        return st == 0 ? 0 : 1;
    }

    printf("ERR bad command\n");
    return 2;
}

/* 父进程守卫: 父进程一消失就自杀。
 *
 * 光靠 stdin EOF 不够 —— GUI 崩了或被任务管理器强杀时, 本进程可能正阻塞在 nvapi
 * 调用里, fgets 永远回不来, 于是留一堆 nvddc32.exe 在任务管理器 (2026-07-30 用户
 * 实际遇到)。开一个线程等父进程句柄, 零轮询、父进程一退立刻走。 */
static DWORD WINAPI parent_watch(LPVOID arg)
{
    WaitForSingleObject((HANDLE)arg, INFINITE);
    ExitProcess(0);
    return 0;
}

static void watch_parent(unsigned long pid)
{
    HANDLE ph = OpenProcess(SYNCHRONIZE, FALSE, (DWORD)pid);
    HANDLE th;
    if (!ph) return;                    /* 拿不到就算了, 还有 stdin EOF 兜着 */
    th = CreateThread(NULL, 0, parent_watch, ph, 0, NULL);
    if (th) CloseHandle(th);
}

/* 常驻模式: 每行一条命令, 每条回一行。父进程一次启动多次收发, 省掉进程/nvapi 初始化开销。 */
static int serve(void)
{
    char line[4096];
    setvbuf(stdout, NULL, _IONBF, 0);       /* 不缓冲, 父进程按行读得到 */
    while (fgets(line, sizeof(line), stdin)) {
        char *argv[64];
        int argc = 0;
        for (char *tok = strtok(line, " \t\r\n"); tok && argc < 64;
             tok = strtok(NULL, " \t\r\n"))
            argv[argc++] = tok;
        if (argc == 0) continue;
        if (_stricmp(argv[0], "quit") == 0 || _stricmp(argv[0], "exit") == 0) break;
        dispatch(argc, argv);
        fflush(stdout);
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        printf("usage: nvddc32 enum | edid <mask> | w <mask> <addr> <hex...> | "
               "r <mask> <addr> <n> | x <mask> <waddr> <raddr> <n> <ms> <hex...> | "
               "serve | list | set <0-100> [mask] | raw <mask> <hex...> | "
               "hscan [mask] | h <handle>\n");
        return 2;
    }
    if (nv_init() != 0) return 10;
    if (_stricmp(argv[1], "serve") == 0) {
        /* serve [父进程 pid]: 带了就盯着它, 它一退本进程立刻退 (防残留) */
        if (argc >= 3) watch_parent(strtoul(argv[2], NULL, 10));
        return serve();
    }
    return dispatch(argc - 1, argv + 1);
}
