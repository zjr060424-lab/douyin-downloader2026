# Design System

## Theme

Competitive desktop launcher. Warm light workspace surfaces are framed by near-black navigation and status areas. Coral red carries the primary action and active progress; sulfur yellow is reserved for system emphasis.

## Color

- Canvas: `oklch(0.92 0.012 65)`
- Workspace: `oklch(0.97 0.012 65)`
- Ink: `oklch(0.22 0.008 60)`
- Rail: `oklch(0.18 0.006 60)`
- Primary: `oklch(0.63 0.22 18)`
- System: `oklch(0.84 0.15 89)`
- Success: `oklch(0.68 0.14 157)`
- Muted text: `oklch(0.52 0.015 65)`

## Typography

Use Microsoft YaHei UI for Chinese and Segoe UI for Latin text. Primary task headings use bold 28-32 px type; controls use 13-15 px; technical labels use 10-11 px uppercase text; logs use Cascadia Mono for timestamps and Microsoft YaHei UI for messages.

## Layout

The window uses a fixed utility rail and an asymmetric main/status split. The coral download composer owns the top of the workspace. Parameters, task progress, output location, and logs follow in workflow order. The status column keeps service, cookie, and ffmpeg readiness visible.

## Components

- Primary download button: near-black on the coral composer, minimum 48 px high.
- Inputs and selects: light surface, 2 px dark border, 4-6 px radius.
- Progress: thick horizontal track with coral fill and a yellow leading marker.
- Status: leading state symbol plus text; never color alone.
- Log: near-black surface with muted timestamps and a green success role.
- Motion: diagonal hero stripes move only while a download is active, using short linear steps. Static presentation remains complete when motion is disabled.
