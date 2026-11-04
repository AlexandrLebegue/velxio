import React from 'react';
import { getProBoard } from '../../lib/proBoardRegistry';
import type { BoardInstance, BoardLedVisuals } from '../../types/board';
import { ArduinoUno } from '../velxio-components/ArduinoUno';
import { ArduinoNano } from '../velxio-components/ArduinoNano';
import { ArduinoMega } from '../velxio-components/ArduinoMega';
// NanoRP2040 (wokwi-nano-rp2040-connect) used to back the 'raspberry-pi-pico'
// boardKind by mistake — kept the import out so future contributors don't
// re-wire it back in. If someone genuinely needs a Nano RP2040 Connect
// board (D2..D13 labels), add a new boardKind 'arduino-nano-rp2040'.
import { RaspberryPiZero } from '../velxio-components/RaspberryPiZero';
import { RaspberryPi1 } from '../velxio-components/RaspberryPi1';
import { RaspberryPi2 } from '../velxio-components/RaspberryPi2';
import { RaspberryPi3 } from '../velxio-components/RaspberryPi3';
import { RaspberryPi4 } from '../velxio-components/RaspberryPi4';
import { RaspberryPi5 } from '../velxio-components/RaspberryPi5';
import { Esp32 } from '../velxio-components/Esp32';
import { Attiny85 } from '../velxio-components/Attiny85';
import { PiPicoW } from '../velxio-components/PiPicoW';
import {
  Stm32BluePill,
  Stm32BlackPill,
  Stm32BluePillF103CB,
  Stm32BlackPillF401,
  Stm32F4Discovery,
  Stm32OlimexH405,
  Stm32NetduinoPlus2,
  Stm32Netduino2,
} from '../velxio-components/Stm32BluePill';

/** The same board rendering is used on canvas and for off-canvas pin inspection. */
export function BoardElement({
  board,
  onboardLeds,
}: {
  board: Pick<BoardInstance, 'id' | 'boardKind' | 'x' | 'y'> & { running?: boolean };
  onboardLeds?: BoardLedVisuals;
}) {
  const { id, boardKind, x, y } = board;
  const led13 = onboardLeds?.led === true;

  // Overlay-registered board (proBoardRegistry): the overlay either provides
  // a render function or we mount its custom element directly — the element
  // was defined by the overlay's import, and pinInfo lives on the DOM node
  // like any other board Web Component.
  const proDef = getProBoard(boardKind);
  if (proDef) {
    if (proDef.render) return proDef.render({ id, x, y, running: !!board.running });
    return React.createElement(proDef.tag, {
      id,
      style: { position: 'absolute', left: x, top: y },
    });
  }
  switch (boardKind) {
    case 'arduino-uno':
      return <ArduinoUno id={id} x={x} y={y} led13={led13} />;
    case 'arduino-nano':
      return <ArduinoNano id={id} x={x} y={y} led13={led13} />;
    case 'arduino-mega':
      return <ArduinoMega id={id} x={x} y={y} led13={led13} />;
    // 'raspberry-pi-pico' used to render <NanoRP2040> (a wokwi-nano-
    // rp2040-connect element with D2-D13 pin labels). That was a
    // misnaming bug — the Nano RP2040 Connect is a different board.
    // Use the same Pico Web Component as 'pi-pico-w' so the pins are
    // labeled GP0..GP28, 3V3, VBUS, etc. — matching the FQBN
    // (rp2040:rp2040:rpipico) and every Pi-Pico sketch's #defines.
    case 'raspberry-pi-pico':
    case 'pi-pico-w':
      return <PiPicoW id={id} x={x} y={y} />;
    // Each Pi draws as itself. Zero/1/2 used to borrow the Pi 3's picture
    // "because the header is the canvas identity" — but the Zero is 65x30 mm
    // against the Pi 3's 85x56, ships its header unpopulated and has neither
    // Ethernet nor full-size USB, so that shortcut drew a board the student
    // was not holding. 1B+ and 2B do share the Pi 3's outline; their silicon
    // and silkscreen do not.
    case 'raspberry-pi-zero':
      return <RaspberryPiZero id={id} x={x} y={y} />;
    case 'raspberry-pi-1':
      return <RaspberryPi1 id={id} x={x} y={y} />;
    case 'raspberry-pi-2':
      return <RaspberryPi2 id={id} x={x} y={y} />;
    case 'raspberry-pi-3':
      return <RaspberryPi3 id={id} x={x} y={y} />;
    case 'raspberry-pi-4':
      return <RaspberryPi4 id={id} x={x} y={y} />;
    case 'raspberry-pi-5':
      return <RaspberryPi5 id={id} x={x} y={y} />;
    case 'esp32':
    case 'esp32-devkit-c-v4':
    case 'esp32-cam':
    case 'wemos-lolin32-lite':
    case 'esp32-s3':
    case 'xiao-esp32-s3':
    case 'arduino-nano-esp32':
    case 'esp32-c3':
    case 'xiao-esp32-c3':
    case 'aitewinrobot-esp32c3-supermini':
      return <Esp32 id={id} x={x} y={y} boardKind={boardKind} onboardLeds={onboardLeds} />;
    case 'stm32-bluepill':
      return <Stm32BluePill id={id} x={x} y={y} />;
    case 'stm32-blackpill':
      return <Stm32BlackPill id={id} x={x} y={y} />;
    case 'stm32-bluepill-f103cb':
      return <Stm32BluePillF103CB id={id} x={x} y={y} />;
    case 'stm32-blackpill-f401':
      return <Stm32BlackPillF401 id={id} x={x} y={y} />;
    case 'stm32-f4-discovery':
      return <Stm32F4Discovery id={id} x={x} y={y} />;
    case 'stm32-olimex-h405':
      return <Stm32OlimexH405 id={id} x={x} y={y} />;
    case 'stm32-netduino-plus2':
      return <Stm32NetduinoPlus2 id={id} x={x} y={y} />;
    case 'stm32-netduino2':
      return <Stm32Netduino2 id={id} x={x} y={y} />;
    case 'attiny85':
      return <Attiny85 id={id} x={x} y={y} led1={led13} />;
  }

  return null;
}
