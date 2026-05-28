import Foundation
import AVFoundation
import CoreGraphics
import ImageIO
import CoreVideo

func fail(_ message: String) -> Never {
    fputs("Error: \(message)\n", stderr)
    exit(1)
}

if CommandLine.arguments.count < 6 {
    fail("Usage: swift png_sequence_to_mp4.swift <frames_dir> <fps> <width> <height> <output_mp4>")
}

let framesDir = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let fps = Int32(CommandLine.arguments[2]) ?? 30
let width = Int(CommandLine.arguments[3]) ?? 1920
let height = Int(CommandLine.arguments[4]) ?? 1080
let outputURL = URL(fileURLWithPath: CommandLine.arguments[5])

let fm = FileManager.default
if fm.fileExists(atPath: outputURL.path) {
    try? fm.removeItem(at: outputURL)
}

guard let enumerator = fm.enumerator(at: framesDir, includingPropertiesForKeys: nil) else {
    fail("Cannot enumerate frames directory")
}

let frames = enumerator.compactMap { $0 as? URL }
    .filter { $0.pathExtension.lowercased() == "png" }
    .sorted { $0.lastPathComponent < $1.lastPathComponent }

if frames.isEmpty {
    fail("No PNG frames found")
}

let writer: AVAssetWriter
do {
    writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
} catch {
    fail("Cannot create AVAssetWriter: \(error)")
}

let settings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: width * height * 6,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel
    ]
]

let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false

let adaptorAttributes: [String: Any] = [
    kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32ARGB),
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height
]

let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: input,
    sourcePixelBufferAttributes: adaptorAttributes
)

guard writer.canAdd(input) else {
    fail("Cannot add video input")
}
writer.add(input)

guard writer.startWriting() else {
    fail("Failed to start writing: \(writer.error?.localizedDescription ?? "unknown")")
}

writer.startSession(atSourceTime: .zero)

func makePixelBuffer(from image: CGImage, width: Int, height: Int) -> CVPixelBuffer? {
    var maybeBuffer: CVPixelBuffer?
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault,
        width,
        height,
        kCVPixelFormatType_32ARGB,
        [
            kCVPixelBufferCGImageCompatibilityKey: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey: true
        ] as CFDictionary,
        &maybeBuffer
    )

    guard status == kCVReturnSuccess, let pixelBuffer = maybeBuffer else {
        return nil
    }

    CVPixelBufferLockBaseAddress(pixelBuffer, [])
    defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }

    guard let context = CGContext(
        data: CVPixelBufferGetBaseAddress(pixelBuffer),
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
    ) else {
        return nil
    }

    context.clear(CGRect(x: 0, y: 0, width: width, height: height))
    context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    return pixelBuffer
}

func cgImage(from url: URL) -> CGImage? {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else {
        return nil
    }
    return CGImageSourceCreateImageAtIndex(source, 0, nil)
}

let queue = DispatchQueue(label: "video.writer.queue")
let frameDuration = CMTime(value: 1, timescale: fps)
var frameIndex: Int64 = 0

let group = DispatchGroup()
group.enter()

input.requestMediaDataWhenReady(on: queue) {
    while input.isReadyForMoreMediaData && frameIndex < Int64(frames.count) {
        let frameURL = frames[Int(frameIndex)]
        guard let image = cgImage(from: frameURL) else {
            fail("Failed to read image \(frameURL.lastPathComponent)")
        }
        guard let buffer = makePixelBuffer(from: image, width: width, height: height) else {
            fail("Failed to create pixel buffer for \(frameURL.lastPathComponent)")
        }
        let time = CMTimeMultiply(frameDuration, multiplier: Int32(frameIndex))
        if !adaptor.append(buffer, withPresentationTime: time) {
            fail("Failed to append frame \(frameURL.lastPathComponent)")
        }
        frameIndex += 1
    }

    if frameIndex >= Int64(frames.count) {
        input.markAsFinished()
        writer.finishWriting {
            if let error = writer.error {
                fail("Finish writing failed: \(error)")
            }
            group.leave()
        }
    }
}

group.wait()
print(outputURL.path)
