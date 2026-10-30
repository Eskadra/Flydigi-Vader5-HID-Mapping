
import hid
import time
import json
from pathlib import Path
from datetime import datetime

VID = 0x37D7
PID = 0x2401
USAGE_PAGE = 0xFFA0
USAGE = 0x01

# Команды из ControlLab / Vader5Protocol.swift
INIT_COMMANDS = [
    bytes.fromhex("5A A5 01 02 03"),
    bytes.fromhex("5A A5 A1 02 A3"),
    bytes.fromhex("5A A5 02 02 04"),
    bytes.fromhex("5A A5 04 02 06"),
    bytes.fromhex("5A A5 11 07 FF 01 FF FF FF 15"),
]

STOP_COMMAND = bytes.fromhex(
    "5A A5 11 07 FF 00 FF FF FF 14"
)

# Название, индекс байта, битовая маска
BUTTONS = [
    ("A", 11, 0x10),
    ("B", 11, 0x20),
    ("X", 11, 0x80),
    ("Y", 12, 0x01),
    ("LB", 12, 0x04),
    ("RB", 12, 0x08),
    ("BACK", 11, 0x40),
    ("START", 12, 0x02),
    ("L3", 12, 0x40),
    ("R3", 12, 0x80),
    ("C", 13, 0x01),
    ("Z", 13, 0x02),
    ("M1", 13, 0x04),
    ("M2", 13, 0x08),
    ("M3", 13, 0x10),
    ("M4", 13, 0x20),
    ("HOME", 14, 0x08),
    ("FN", 14, 0x01),
    ("LM", 13, 0x40),
    ("RM", 13, 0x80),
]

RESULT_FILE = Path("flydigi_mapping.json")


def open_controller():
    devices = hid.enumerate(VID, PID)

    for info in devices:
        if (
            info["usage_page"] == USAGE_PAGE
            and info["usage"] == USAGE
        ):
            dev = hid.device()
            dev.open_path(info["path"])
            dev.set_nonblocking(True)
            return dev

    raise RuntimeError(
        "Интерфейс Flydigi 0xFFA0/0x01 не найден"
    )


def send_command(dev, command):
    # HIDAPI: нулевой Report ID перед 32-байтным
    # Output Report. На macOS это необходимо проверить.
    payload = command.ljust(32, b"\x00")
    result = dev.write(b"\x00" + payload)

    if result <= 0:
        raise RuntimeError(
            f"Не удалось отправить {command.hex(' ')}"
        )

    print(
        "[TX]",
        command.hex(" ").upper(),
        f"({result} байт)"
    )


def initialize(dev):
    print("\nИнициализация Flydigi...")

    for command in INIT_COMMANDS:
        send_command(dev, command)
        time.sleep(0.06)

    print("Команды инициализации отправлены.")


def read_state(dev, timeout=0.1):
    end = time.monotonic() + timeout

    while time.monotonic() < end:
        data = dev.read(64)

        if not data:
            time.sleep(0.002)
            continue

        data = bytes(data)

        # Игровой отчёт ControlLab
        if (
            len(data) >= 29
            and data[:3] == b"\x5A\xA5\xEF"
        ):
            return data

    return None


def pressed(data, offset, mask):
    return bool(data[offset] & mask)


def wait_button(dev, name, offset, mask):
    print(f"\n>>> Нажми кнопку: {name}")

    deadline = time.monotonic() + 30

    while time.monotonic() < deadline:
        data = read_state(dev)

        if data is None:
            continue

        if pressed(data, offset, mask):
            print(f"[OK] {name} нажата")
            print("REPORT:", data.hex(" ").upper())

            # Ожидаем отпускание
            while time.monotonic() < deadline:
                released = read_state(dev)

                if released is None:
                    continue

                if not pressed(released, offset, mask):
                    print(f"[OK] {name} отпущена")
                    return {
                        "button": name,
                        "byte": offset,
                        "mask": f"0x{mask:02X}",
                        "pressed_report": data.hex(" "),
                        "released_report": released.hex(" "),
                    }

            print("[TIMEOUT] Отпускание не обнаружено")
            return None

    print("[TIMEOUT] Нажатие не обнаружено")
    return None


def save_results(results):
    document = {
        "device": "Flydigi Vader 5 Pro",
        "vid": f"0x{VID:04X}",
        "pid": f"0x{PID:04X}",
        "timestamp": datetime.now().isoformat(),
        "results": results,
    }

    RESULT_FILE.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(f"\nСохранено: {RESULT_FILE.resolve()}")


def main():
    dev = None
    initialized = False
    results = []

    try:
        dev = open_controller()
        print("Flydigi Vader 5 Pro найден")

        initialize(dev)
        initialized = True

        print("\nОжидание игровых пакетов...")

        first = None
        deadline = time.monotonic() + 10

        while time.monotonic() < deadline:
            first = read_state(dev)
            if first is not None:
                break

        if first is None:
            print(
                "Нет пакетов 5A A5 EF. "
                "Возможна несовместимость HIDAPI "
                "Output Report с macOS."
            )
            return

        print("Получен игровой пакет!")
        print(first.hex(" ").upper())

        for index, (name, offset, mask) in enumerate(
            BUTTONS, 1
        ):
            print(
                f"\n[{index}/{len(BUTTONS)}] "
                f"Тест {name}"
            )

            result = wait_button(
                dev, name, offset, mask
            )

            if result:
                results.append(result)

    except KeyboardInterrupt:
        print("\nТест остановлен.")

    except Exception as exc:
        print("\nОшибка:", exc)

    finally:
        if dev is not None:
            if initialized:
                try:
                    send_command(dev, STOP_COMMAND)
                except Exception as exc:
                    print("Ошибка остановки:", exc)

            dev.close()

        save_results(results)


if __name__ == "__main__":
    main()
