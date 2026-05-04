#!/usr/bin/env node
// PearPost integration for Iris.
// Uses Iris' own PEARPOST_HOME and forces process exit after one-shot commands
// because Hyperswarm/Corestore teardown can otherwise keep Claude invocations alive.

import { Agent } from '../pearpost/protocol/index.js'

const PROJECT_ROOT = '/home/iris/executive-assistant'
const HOME = process.env.PEARPOST_HOME || `${PROJECT_ROOT}/workspace/state/pearpost`
const ALIAS = process.env.PEARPOST_ALIAS || 'iris'
const SEMANTIC_NOISE = new Set(['presence', 'ack'])

function usage () {
  console.log(`pearpost.mjs — Iris P2P messaging

Usage:
  node integrations/pearpost.mjs address
  node integrations/pearpost.mjs contacts
  node integrations/pearpost.mjs add <pear+agent://...> [alias]
  node integrations/pearpost.mjs chat <pear+agent://...> <text...>
  node integrations/pearpost.mjs send <pear+agent://...> <type> <json-body>
  node integrations/pearpost.mjs list [n] [--bucket=main|requests|all]
  node integrations/pearpost.mjs requests [n]

Defaults:
  PEARPOST_HOME=${HOME}
  PEARPOST_ALIAS=${ALIAS}`)
}

function addressFromPubHex (pubHex) {
  return `pear+agent://${pubHex}`
}

function simplifyMessage (rec) {
  return {
    key: rec.key,
    bucket: rec.bucket || 'main',
    id: rec.env?.id,
    time: rec.env?.ts ? new Date(rec.env.ts).toISOString() : null,
    from: rec.env?.from,
    to: rec.env?.to,
    type: rec.env?.type,
    inReplyTo: rec.env?.inReplyTo,
    body: rec.body || rec.env?.body
  }
}

async function withAgent (fn) {
  const agent = new Agent(HOME, {
    profile: { alias: ALIAS },
    directory: false,
    presence: false
  })

  process.env.PEARPOST_SKIP_FLUSH = '1'
  await agent.start()
  try {
    return await fn(agent)
  } finally {
    // Best effort: do not let slow Hyperswarm teardown hang the invoking Claude run.
    const stop = agent.stop().catch(() => {})
    await Promise.race([stop, new Promise(resolve => setTimeout(resolve, 1500))])
  }
}

async function main () {
  const [cmd, ...args] = process.argv.slice(2)
  if (!cmd || cmd === 'help' || cmd === '--help' || cmd === '-h') {
    usage()
    return
  }

  const result = await withAgent(async (agent) => {
    if (cmd === 'address' || cmd === 'id') {
      return { alias: ALIAS, address: addressFromPubHex(agent.pubHex), pubHex: agent.pubHex, home: HOME }
    }

    if (cmd === 'contacts') {
      return await agent.contacts()
    }

    if (cmd === 'add') {
      const [addr, alias] = args
      if (!addr) throw new Error('Usage: add <pear+agent://...> [alias]')
      return await agent.addContact(addr, alias)
    }

    if (cmd === 'chat') {
      const [addr, ...textParts] = args
      if (!addr || textParts.length === 0) throw new Error('Usage: chat <pear+agent://...> <text...>')
      const env = await agent.chat(addr, textParts.join(' '))
      return { id: env.id, to: env.to, type: env.type, ts: env.ts }
    }

    if (cmd === 'send') {
      const [addr, type, jsonBody] = args
      if (!addr || !type || !jsonBody) throw new Error('Usage: send <pear+agent://...> <type> <json-body>')
      const body = JSON.parse(jsonBody)
      const env = await agent.send(addr, type, body)
      return { id: env.id, to: env.to, type: env.type, ts: env.ts }
    }

    if (cmd === 'list') {
      const n = Number.parseInt(args.find(a => /^\d+$/.test(a)) || '20', 10)
      const bucketArg = args.find(a => a.startsWith('--bucket='))
      const waitArg = args.find(a => a.startsWith('--wait-ms='))
      const bucket = bucketArg ? bucketArg.slice('--bucket='.length) : 'main'
      const waitMs = waitArg ? Number.parseInt(waitArg.slice('--wait-ms='.length), 10) : 3000
      if (waitMs > 0) await new Promise(resolve => setTimeout(resolve, waitMs))
      const msgs = await agent.messages({ limit: n, reverse: true, bucket })
      return msgs.filter(r => !SEMANTIC_NOISE.has(r?.env?.type)).map(simplifyMessage)
    }

    if (cmd === 'requests') {
      const n = Number.parseInt(args.find(a => /^\d+$/.test(a)) || '20', 10)
      const waitArg = args.find(a => a.startsWith('--wait-ms='))
      const waitMs = waitArg ? Number.parseInt(waitArg.slice('--wait-ms='.length), 10) : 3000
      if (waitMs > 0) await new Promise(resolve => setTimeout(resolve, waitMs))
      const msgs = await agent.requests({ limit: n, reverse: true })
      return msgs.filter(r => !SEMANTIC_NOISE.has(r?.env?.type)).map(simplifyMessage)
    }

    throw new Error(`Unknown command: ${cmd}`)
  })

  console.log(JSON.stringify(result, null, 2))
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(JSON.stringify({ error: err.message || String(err) }, null, 2))
    process.exit(1)
  })
