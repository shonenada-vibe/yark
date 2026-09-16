# yark Windows helper. Called from WSL or native Windows Python.
# Modes:
#   keys  — poll hold-to-talk keys, print "YARK keys …" lines
#   mic   — capture default recording device as 16-bit PCM, print "YARK pcm <b64>"
param(
    [ValidateSet("keys", "mic")]
    [string]$Mode = "keys",
    [int]$Rate = 16000,
    [int]$ChunkMs = 200
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = [Console]::OutputEncoding

if ($Mode -eq "keys") {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class YarkKeys {
    [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int vKey);
}
"@

    $vk = [ordered]@{
        left_shift     = 0xA0
        right_shift    = 0xA1
        left_control   = 0xA2
        right_control  = 0xA3
        left_option    = 0xA4
        right_option   = 0xA5
        left_command   = 0x5B
        right_command  = 0x5C
        space          = 0x20
        f8             = 0x77
        f9             = 0x78
        f13            = 0x7C
        f14            = 0x7D
        f15            = 0x7E
        f16            = 0x7F
        f17            = 0x80
        f18            = 0x81
        f19            = 0x82
    }

    $prev = $null
    while ($true) {
        $down = New-Object System.Collections.Generic.List[string]
        foreach ($name in $vk.Keys) {
            if ([YarkKeys]::GetAsyncKeyState([int]$vk[$name]) -band 0x8000) {
                [void]$down.Add($name)
            }
        }
        if ((-not $down.Contains("left_option")) -and (-not $down.Contains("right_option"))) {
            if ([YarkKeys]::GetAsyncKeyState(0x12) -band 0x8000) { [void]$down.Add("option") }
        }
        if ((-not $down.Contains("left_control")) -and (-not $down.Contains("right_control"))) {
            if ([YarkKeys]::GetAsyncKeyState(0x11) -band 0x8000) { [void]$down.Add("control") }
        }
        if ((-not $down.Contains("left_shift")) -and (-not $down.Contains("right_shift"))) {
            if ([YarkKeys]::GetAsyncKeyState(0x10) -band 0x8000) { [void]$down.Add("shift") }
        }
        for ($code = 0x41; $code -le 0x5A; $code++) {
            if ([YarkKeys]::GetAsyncKeyState($code) -band 0x8000) {
                [void]$down.Add([char]$code)
            }
        }
        $line = "YARK keys"
        if ($down.Count -gt 0) {
            $line = "YARK keys " + ($down -join " ")
        }
        if ($line -ne $prev) {
            $prev = $line
            [Console]::Out.WriteLine($line)
            [Console]::Out.Flush()
        }
        Start-Sleep -Milliseconds 15
    }
    return
}

Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public class YarkWaveIn {
    const uint WAVE_MAPPER = 0xFFFFFFFF;
    const uint CALLBACK_FUNCTION = 0x00030000;
    const int MM_WIM_DATA = 0x3C0;

    [StructLayout(LayoutKind.Sequential)]
    struct WAVEFORMATEX {
        public short wFormatTag;
        public short nChannels;
        public int nSamplesPerSec;
        public int nAvgBytesPerSec;
        public short nBlockAlign;
        public short wBitsPerSample;
        public short cbSize;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct WAVEHDR {
        public IntPtr lpData;
        public int dwBufferLength;
        public int dwBytesRecorded;
        public IntPtr dwUser;
        public int dwFlags;
        public int dwLoops;
        public IntPtr lpNext;
        public IntPtr reserved;
    }

    delegate void WaveInProc(IntPtr hwi, int uMsg, IntPtr dwInstance, IntPtr dwParam1, IntPtr dwParam2);

    [DllImport("winmm.dll")] static extern int waveInOpen(out IntPtr ph, uint id, ref WAVEFORMATEX fmt, WaveInProc cb, IntPtr inst, uint flags);
    [DllImport("winmm.dll")] static extern int waveInPrepareHeader(IntPtr h, IntPtr hdr, int size);
    [DllImport("winmm.dll")] static extern int waveInUnprepareHeader(IntPtr h, IntPtr hdr, int size);
    [DllImport("winmm.dll")] static extern int waveInAddBuffer(IntPtr h, IntPtr hdr, int size);
    [DllImport("winmm.dll")] static extern int waveInStart(IntPtr h);
    [DllImport("winmm.dll")] static extern int waveInStop(IntPtr h);
    [DllImport("winmm.dll")] static extern int waveInReset(IntPtr h);
    [DllImport("winmm.dll")] static extern int waveInClose(IntPtr h);

    IntPtr handle = IntPtr.Zero;
    WaveInProc proc;
    GCHandle[] pins;
    IntPtr[] hdrs;
    readonly Queue<byte[]> q = new Queue<byte[]>();
    readonly object gate = new object();
    int hdrSize;

    public void Start(int rate, int chunkBytes) {
        proc = Callback;
        hdrSize = Marshal.SizeOf(typeof(WAVEHDR));
        WAVEFORMATEX fmt = new WAVEFORMATEX();
        fmt.wFormatTag = 1;
        fmt.nChannels = 1;
        fmt.nSamplesPerSec = rate;
        fmt.wBitsPerSample = 16;
        fmt.nBlockAlign = 2;
        fmt.nAvgBytesPerSec = rate * 2;
        fmt.cbSize = 0;
        int err = waveInOpen(out handle, WAVE_MAPPER, ref fmt, proc, IntPtr.Zero, CALLBACK_FUNCTION);
        if (err != 0) throw new Exception("waveInOpen failed " + err);
        pins = new GCHandle[2];
        hdrs = new IntPtr[2];
        for (int i = 0; i < 2; i++) {
            byte[] buf = new byte[chunkBytes];
            pins[i] = GCHandle.Alloc(buf, GCHandleType.Pinned);
            hdrs[i] = Marshal.AllocHGlobal(hdrSize);
            WAVEHDR hdr = new WAVEHDR();
            hdr.lpData = pins[i].AddrOfPinnedObject();
            hdr.dwBufferLength = chunkBytes;
            Marshal.StructureToPtr(hdr, hdrs[i], false);
            waveInPrepareHeader(handle, hdrs[i], hdrSize);
            waveInAddBuffer(handle, hdrs[i], hdrSize);
        }
        err = waveInStart(handle);
        if (err != 0) throw new Exception("waveInStart failed " + err);
    }

    void Callback(IntPtr hwi, int uMsg, IntPtr dwInstance, IntPtr dwParam1, IntPtr dwParam2) {
        if (uMsg != MM_WIM_DATA || dwParam1 == IntPtr.Zero) return;
        WAVEHDR hdr = (WAVEHDR)Marshal.PtrToStructure(dwParam1, typeof(WAVEHDR));
        int n = hdr.dwBytesRecorded;
        if (n > 0 && hdr.lpData != IntPtr.Zero) {
            byte[] copy = new byte[n];
            Marshal.Copy(hdr.lpData, copy, 0, n);
            lock (gate) { q.Enqueue(copy); }
        }
        waveInAddBuffer(hwi, dwParam1, hdrSize);
    }

    public byte[] Take() {
        lock (gate) {
            if (q.Count == 0) return null;
            return q.Dequeue();
        }
    }

    public void Stop() {
        if (handle == IntPtr.Zero) return;
        waveInStop(handle);
        waveInReset(handle);
        if (hdrs != null) {
            for (int i = 0; i < hdrs.Length; i++) {
                if (hdrs[i] != IntPtr.Zero) {
                    waveInUnprepareHeader(handle, hdrs[i], hdrSize);
                    Marshal.FreeHGlobal(hdrs[i]);
                    hdrs[i] = IntPtr.Zero;
                }
            }
        }
        if (pins != null) {
            for (int i = 0; i < pins.Length; i++) {
                if (pins[i].IsAllocated) pins[i].Free();
            }
        }
        waveInClose(handle);
        handle = IntPtr.Zero;
    }
}
"@

$chunkBytes = [Math]::Max(1, [int]($Rate * 2 * $ChunkMs / 1000))
$mic = New-Object YarkWaveIn
try {
    $mic.Start($Rate, $chunkBytes)
    [Console]::Error.WriteLine("YARK mic started rate=$Rate chunk_ms=$ChunkMs")
    while ($true) {
        $chunk = $mic.Take()
        if ($chunk -ne $null -and $chunk.Length -gt 0) {
            [Console]::Out.WriteLine("YARK pcm " + [Convert]::ToBase64String($chunk))
            [Console]::Out.Flush()
        }
        else {
            Start-Sleep -Milliseconds 10
        }
    }
}
finally {
    $mic.Stop()
}
