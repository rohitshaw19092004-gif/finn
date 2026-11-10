/** Voice, using only what the phone already has (no audio leaves the device, no cost). */

export function speak(lines: string[], onEnd?: () => void): () => void {
  const synth = window.speechSynthesis;
  if (!synth) { onEnd?.(); return () => {}; }
  synth.cancel();
  const voices = synth.getVoices();
  const voice = voices.find((v) => /en-IN/i.test(v.lang)) ?? voices.find((v) => /^en/i.test(v.lang));
  lines.forEach((t, i) => {
    const u = new SpeechSynthesisUtterance(t);
    if (voice) u.voice = voice;
    u.rate = 1.04;
    if (i === lines.length - 1) u.onend = () => onEnd?.();
    synth.speak(u);
  });
  return () => synth.cancel();
}

export const canListen = () => typeof window !== "undefined" && ("webkitSpeechRecognition" in window || "SpeechRecognition" in window);

export function listen(onText: (t: string, final: boolean) => void, onEnd: () => void): () => void {
  const W = window as any;
  const R = W.SpeechRecognition || W.webkitSpeechRecognition;
  if (!R) { onEnd(); return () => {}; }
  const rec = new R();
  rec.lang = "en-IN";
  rec.interimResults = true;
  rec.onresult = (e: any) => {
    const r = e.results[e.results.length - 1];
    onText(r[0].transcript, r.isFinal);
  };
  rec.onend = onEnd;
  rec.onerror = onEnd;
  rec.start();
  return () => rec.stop();
}
