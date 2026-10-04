import Cocoa
let folder = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
for (name, size) in [("icon_16x16.png",16),("icon_16x16@2x.png",32),("icon_32x32.png",32),("icon_32x32@2x.png",64),("icon_128x128.png",128),("icon_128x128@2x.png",256),("icon_256x256.png",256),("icon_256x256@2x.png",512),("icon_512x512.png",512),("icon_512x512@2x.png",1024)] {
 let n = CGFloat(size)
 let rep = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:size,pixelsHigh:size,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
 NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep:rep)
 let rect=NSRect(x:n*0.08,y:n*0.08,width:n*0.84,height:n*0.84)
 let shape=NSBezierPath(roundedRect:rect,xRadius:n*0.19,yRadius:n*0.19)
 let gradient=NSGradient(starting:NSColor(red:0.13,green:0.33,blue:0.87,alpha:1),ending:NSColor(red:0.33,green:0.66,blue:1,alpha:1))!
 gradient.draw(in:shape,angle:70)
 let play=NSBezierPath();play.move(to:NSPoint(x:n*0.40,y:n*0.30));play.line(to:NSPoint(x:n*0.72,y:n*0.50));play.line(to:NSPoint(x:n*0.40,y:n*0.70));play.close();NSColor.white.setFill();play.fill()
 NSGraphicsContext.restoreGraphicsState()
 try rep.representation(using:.png,properties:[:])!.write(to:folder.appendingPathComponent(name))
}
