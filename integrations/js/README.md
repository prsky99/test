# agent-concierge (JavaScript)

```js
import { searchAgents } from 'agent-concierge';
const agents = await searchAgents('japanese weather forecast', { protocol: 'mcp', checkedOnly: true });
```

Each result carries its latest recorded check. A check records what happened when it ran; it does not guarantee that an agent works now. Full MCP setup: https://agentconcierge.biz/connect
