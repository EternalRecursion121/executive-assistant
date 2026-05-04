#!/usr/bin/env node
// PearPost watcher daemon for Iris.
// Keeps a persistent PearPost connection and writes incoming messages to a wake spool.
// The main bot can poll this spool, or a separate service can invoke Claude on new messages.

import fs from 'fs'
import path from 'path'
import { Agent } from '../pearpost/protocol/index.js'

const PROJECT_ROOT = '/home/iris/executive-assistant'
const HOME = process.env.PEARPOST_HOME || `${PROJECT_ROOT}/workspace/state/pearpost`
const WAKE_SPOOL = process.env.PEARPOST_WAKE_SPOOL || `${PROJECT_ROOT}/workspace/state/pearpost_wake.jsonl`
const OUTBOX_SPOOL = `${PROJECT_ROOT}/workspace/state/pearpost_outbox.jsonl`
const PROCESSED_FILE = `${PROJECT_ROOT}/workspace/state/pearpost_processed.json`
const ALIAS = 'iris'

// Message types that should NOT trigger a wake
const SEMANTIC_NOISE = new Set(['presence', 'ack'])

// Load processed message IDs to avoid re-triggering
function loadProcessed () {
  try {
    return new Set(JSON.parse(fs.readFileSync(PROCESSED_FILE, 'utf8')))
  } catch {
    return new Set()
  }
}

function saveProcessed (processed) {
  // Keep only last 1000 IDs to prevent unbounded growth
  const arr = [...processed].slice(-1000)
  fs.writeFileSync(PROCESSED_FILE, JSON.stringify(arr, null, 2))
}

function appendToSpool (record) {
  fs.appendFileSync(WAKE_SPOOL, JSON.stringify(record) + '\n')
}

function simplifyMessage (rec) {
  return {
    id: rec.env?.id,
    time: rec.env?.ts ? new Date(rec.env.ts).toISOString() : new Date().toISOString(),
    from: rec.env?.from,
    to: rec.env?.to,
    type: rec.env?.type,
    inReplyTo: rec.env?.inReplyTo,
    body: rec.body || rec.env?.body,
    bucket: rec.bucket || 'main'
  }
}

async function main () {
  console.log(`[pearpost-watcher] Starting...`)
  console.log(`[pearpost-watcher] HOME: ${HOME}`)
  console.log(`[pearpost-watcher] WAKE_SPOOL: ${WAKE_SPOOL}`)

  // Ensure directories exist
  fs.mkdirSync(path.dirname(WAKE_SPOOL), { recursive: true })

  const processed = loadProcessed()
  console.log(`[pearpost-watcher] Loaded ${processed.size} processed message IDs`)

  const agent = new Agent(HOME, {
    profile: { alias: ALIAS },
    directory: true,
    presence: true,
    ack: true
  })

  await agent.start()
  console.log(`[pearpost-watcher] Agent started: ${agent.pubHex}`)

  agent.on('message', (rec) => {
    const msg = simplifyMessage(rec)

    // Skip noise types (don't even log)
    if (SEMANTIC_NOISE.has(msg.type)) {
      return
    }

    // Skip our own messages (echoes)
    if (msg.from === agent.pubHex) {
      return
    }

    // Skip already processed
    if (msg.id && processed.has(msg.id)) {
      console.log(`[pearpost-watcher] Already processed: ${msg.id}`)
      return
    }

    console.log(`[pearpost-watcher] New message: ${msg.type} from ${msg.from?.slice(0, 8)}...`)
    console.log(`[pearpost-watcher] Body: ${JSON.stringify(msg.body).slice(0, 100)}...`)

    // Record to spool
    appendToSpool({
      ...msg,
      received_at: new Date().toISOString()
    })

    // Mark processed
    if (msg.id) {
      processed.add(msg.id)
      saveProcessed(processed)
    }
  })

  agent.on('error', (err) => {
    console.error(`[pearpost-watcher] Error: ${err.message}`)
  })

  // Process outbox spool - messages and commands queued for processing
  async function processOutbox () {
    if (!fs.existsSync(OUTBOX_SPOOL)) return

    const content = fs.readFileSync(OUTBOX_SPOOL, 'utf8').trim()
    if (!content) return

    fs.writeFileSync(OUTBOX_SPOOL, '') // Clear immediately

    for (const line of content.split('\n')) {
      if (!line.trim()) continue
      try {
        const entry = JSON.parse(line)

        // Handle commands (prefixed with _cmd)
        if (entry._cmd === 'add_contact') {
          const { address, alias } = entry
          const fullAddr = address.startsWith('pear+agent://') ? address : `pear+agent://${address}`
          await agent.addContact(fullAddr, alias || undefined)
          console.log(`[pearpost-watcher] Added contact: ${address.slice(0, 16)}...` + (alias ? ` (${alias})` : ''))
          continue
        }

        // Handle messages
        const { to, type, body, text } = entry
        if (type === 'chat' && text) {
          const env = await agent.chat(to, text)
          console.log(`[pearpost-watcher] Sent chat to ${to.slice(0, 16)}...: ${env.id}`)
        } else if (to && type && body) {
          const env = await agent.send(to, type, body)
          console.log(`[pearpost-watcher] Sent ${type} to ${to.slice(0, 16)}...: ${env.id}`)
        }
      } catch (err) {
        console.error(`[pearpost-watcher] Error processing outbox: ${err.message}`)
      }
    }
  }

  // Poll outbox every 2 seconds
  setInterval(processOutbox, 2000)

  // Heartbeat
  setInterval(() => {
    console.log(`[pearpost-watcher] Heartbeat - still running, ${processed.size} messages seen`)
  }, 60000)

  // Graceful shutdown
  process.on('SIGTERM', async () => {
    console.log('[pearpost-watcher] SIGTERM received, shutting down...')
    await agent.stop()
    process.exit(0)
  })

  process.on('SIGINT', async () => {
    console.log('[pearpost-watcher] SIGINT received, shutting down...')
    await agent.stop()
    process.exit(0)
  })

  console.log('[pearpost-watcher] Listening for messages...')
}

main().catch((err) => {
  console.error(`[pearpost-watcher] Fatal: ${err.message}`)
  process.exit(1)
})
