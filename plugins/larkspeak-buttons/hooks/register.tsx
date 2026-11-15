import type { Register } from 'claude-code'

const SERVER = 'tts'

type Action = {
  id: string
  glyph: string
  label: string
  tool: string
}

const CONTROLS: readonly Action[] = [
  { id: 'pause', glyph: '⏸', label: 'Pause speech', tool: 'pause_speech' },
  { id: 'continue', glyph: '▶', label: 'Continue speech', tool: 'resume_speech' },
  { id: 'stop', glyph: '⏹', label: 'Stop speech', tool: 'stop_speech' },
]

export const register: Register = on => {
  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const text = e.props.text
    if (e.props.isSummary || !text || !text.trim()) {
      return next(e)
    }

    const { Box, Button, Text } = $.ui.resolve(e)

    const call = async (tool: string, args: Record<string, unknown>, label: string) => {
      try {
        const result = await $.mcp.call(SERVER, tool, args)
        if (result.isError) {
          $.ui.toast(`${label} failed`)
        }
      } catch {
        $.ui.toast(`${label}: the tts server is not connected`)
      }
    }

    // One keyed Box per button. Its hint is an absolutely positioned Box above the icon, hidden
    // until the keyed Box is hovered, so it takes no room and the icons sit side by side.
    const item = (id: string, glyph: string, label: string, press: () => void) => (
      <Box key={`larkspeak-box-${id}`} position="relative">
        <Button key={`larkspeak-${id}`} plain dimColor label={glyph} onPress={press} />
        <Box
          position="absolute"
          top={-1}
          left={0}
          width={label.length + 2}
          paddingX={1}
          display="none"
          hover={{ display: 'flex' }}
        >
          <Text color="inactive">{label}</Text>
        </Box>
      </Box>
    )

    return (
      <Box flexDirection="column">
        {await next(e)}
        <Box flexDirection="row" gap={1} marginTop={2}>
          {item('read', '\u{1F50A}', 'Read aloud (local)', () => call('start_speech', { text }, 'Read aloud (local)'))}
          {CONTROLS.map(c => item(c.id, c.glyph, c.label, () => call(c.tool, {}, c.label)))}
        </Box>
      </Box>
    )
  })
}
