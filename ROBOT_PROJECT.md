# AI Travel Companion Robot — Project Notes

## Vision

A roaming AI robot that acts as a travel companion — observing its environment, commenting on things of interest, knowing where it is, and launching drones for aerial exploration.

Working name: **Alzar-on-Wheels** (TBD)

## Hardware Stack

### Ground Platform: Xiaomi Robot Vacuum S40C
- Already has: LiDAR (360° LDS navigation), differential drive wheels, cliff sensors, bumper, ultrasonic sensor
- Already has: WiFi (2.4GHz), 14.4V battery (2600mAh), ~120min runtime
- Interface via: `python-miio` Python library (talks directly to Xiaomi robots)
- **Brain addon:** Raspberry Pi mounted on top
- **Eyes:** Raspberry Pi camera module (ground-level)
- **Location:** GPS module (add-on)
- **Voice:** Speaker (TTS output) + Microphone (voice input)
- **Drone bay:** Flat launch/landing platform on top of S40C

### Drone: iFlight Defender 20 Lite (candidate)
- 108g (sub-250g — compliant with Australian CASA regulations)
- 4K60 video with DJI O4 transmission
- USB-C charging — can integrate with robot power system
- Compact enough to land/launch from S40C top platform
- Camera feed piped through AI commentary pipeline

## Software Stack

### AI Pipeline
1. Camera captures scene (ground or drone)
2. Vision model identifies objects, landmarks, text, people
3. GPS + reverse geocoding adds location context (Wikipedia, Google Places, local history)
4. LLM generates commentary
5. TTS speaks it aloud

### Commentary Modes
- **On-demand:** User asks a question → robot answers
- **Talkative mode:** Robot comments freely and frequently — for quiet exploration times
- **Normal mode:** Comments only when something notable is spotted

### Web Interface
- Live camera feed (ground + drone)
- GPS map with track history
- Commentary transcript / log
- Controls: movement, mode switching (talkative/normal/quiet)
- Drone status and control

## Open Questions
- [ ] Vacuum cleaner model/brand (for parts inventory)
- [ ] Drone platform choice
- [ ] Irwin's coding background (Python?)
- [ ] Connectivity: WiFi only, or 4G/cellular for field use?
- [ ] Battery/power strategy (runtime goals?)
- [ ] Offline vs cloud AI (Pi can run small local models)

## Status
- 2026-02-26: Project defined. Architecture sketched. Building started.
