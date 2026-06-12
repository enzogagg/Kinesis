import Quartz

let NX_KEYTYPE_PLAY: Int32 = 16
let eventDown = NSEvent.otherEvent(with: .systemDefined, location: NSPoint(x:0,y:0), modifierFlags: NSEvent.ModifierFlags(rawValue: 0xa00), timestamp: 0, windowNumber: 0, context: nil, subtype: 8, data1: Int((NX_KEYTYPE_PLAY << 16) | ((0xa & 0xff) << 8)), data2: -1)
let eventUp = NSEvent.otherEvent(with: .systemDefined, location: NSPoint(x:0,y:0), modifierFlags: NSEvent.ModifierFlags(rawValue: 0xb00), timestamp: 0, windowNumber: 0, context: nil, subtype: 8, data1: Int((NX_KEYTYPE_PLAY << 16) | ((0xb & 0xff) << 8)), data2: -1)

eventDown?.cgEvent?.post(tap: .cghidEventTap)
eventUp?.cgEvent?.post(tap: .cghidEventTap)
