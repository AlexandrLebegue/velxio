/**
 * WireRenderer — purely visual renderer for a single wire.
 * All interaction (click/hover/drag) is handled by SimulatorCanvas.
 */

import React from 'react';
import type { Wire } from '../../types/wire';
import { generateOrthogonalPath } from '../../utils/wireUtils';
import { cssVar } from '../../lib/theme';
import { useTranslation } from 'react-i18next';
import { useWireDiagnosticsStore } from '../../store/useWireDiagnosticsStore';
import { readPinInfo } from '../../utils/readPinInfo';
import { resolvePinDescriptor, type PinDescriptor } from '../../utils/pinPositionCalculator';

interface WireRendererProps {
  wire: Wire;
  isSelected: boolean;
  isHovered: boolean;
  /** Temporary waypoints used during drag preview */
  previewWaypoints?: { x: number; y: number }[];
  /** Override the full SVG path string (used during segment drag preview) */
  overridePath?: string;
}

export const WireRenderer: React.FC<WireRendererProps> = ({
  wire,
  isSelected,
  isHovered,
  previewWaypoints,
  overridePath,
}) => {
  const { t } = useTranslation();
  const recorded = useWireDiagnosticsStore((state) => state.errors[wire.id]);
  // Imported projects may predate agent validation. Once a part exposes its
  // pads, a stale coordinate must not make an unknown pin look connected.
  const unresolved = (['start', 'end'] as const).find((side) => {
    const endpoint = wire[side];
    const element = document.getElementById(endpoint.componentId);
    const pins = element && readPinInfo<PinDescriptor>(element);
    return pins?.length && !resolvePinDescriptor(pins, endpoint.pinName);
  });
  const diagnostic = unresolved
    ? { endpoint: unresolved, pin: wire[unresolved].pinName }
    : recorded;
  const invalid = diagnostic && wire[diagnostic.endpoint].pinName === diagnostic.pin;
  // Breadboard seating wires are pure connectivity — the part visually
  // sits in the holes, so there is nothing to draw.
  if (wire.bb) return null;

  const waypoints = previewWaypoints ?? wire.waypoints;
  const path = overridePath ?? generateOrthogonalPath(wire.start, waypoints, wire.end);

  if (!path) return null;

  const color = invalid ? cssVar('--color-feedback-error') : wire.color;
  // Wire COLOUR is the user's; the outline, the hover wash and the selection
  // dashes are canvas chrome and follow the theme. On a light canvas the old
  // near-black outline read as a heavy shadow around every run, and the white
  // hover/selection strokes were invisible outright.
  const outline = cssVar('--color-wire-outline');
  const marker = cssVar('--color-wire-marker');
  const strokeW = isSelected ? 3 : 2;
  const outlineW = isSelected ? 6 : 5;
  const opacity = isSelected || isHovered ? 1 : 0.85;

  return (
    <g
      data-wire-id={wire.id}
      data-wire-start={`${wire.start.componentId}:${wire.start.pinName}`}
      data-wire-end={`${wire.end.componentId}:${wire.end.pinName}`}
      data-wire-invalid={invalid ? 'true' : undefined}
      style={{ pointerEvents: 'none' }}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {invalid && (
        <title>
          {t('agent.unresolvedPin')}: {wire.start.componentId}:{wire.start.pinName} →{' '}
          {wire.end.componentId}:{wire.end.pinName}
        </title>
      )}
      {/* Contrast outline, so wires stay readable where they cross */}
      <path d={path} stroke={outline} strokeWidth={outlineW} fill="none" />

      {/* Hover highlight (below wire) */}
      {isHovered && !isSelected && (
        <path d={path} stroke={marker} strokeWidth="6" fill="none" opacity="0.2" />
      )}

      {/* Visible wire */}
      <path
        d={path}
        stroke={color}
        strokeWidth={strokeW}
        fill="none"
        opacity={opacity}
        strokeDasharray={invalid ? '5,4' : undefined}
      />
      {invalid && (
        <text
          x={wire[diagnostic.endpoint].x + 6}
          y={wire[diagnostic.endpoint].y - 7}
          fill={color}
          fontSize="10"
        >
          {t('agent.unresolvedPin')}
        </text>
      )}

      {/* Selection dashed highlight */}
      {isSelected && (
        <path
          d={path}
          stroke={marker}
          strokeWidth="1.5"
          fill="none"
          strokeDasharray="6,4"
          opacity="0.6"
        />
      )}

      {/* Endpoint dots */}
      <circle
        cx={wire.start.x}
        cy={wire.start.y}
        r="3"
        fill={color}
        stroke="#1a1a1a"
        strokeWidth="1"
      />
      <circle cx={wire.end.x} cy={wire.end.y} r="3" fill={color} stroke="#1a1a1a" strokeWidth="1" />
    </g>
  );
};
