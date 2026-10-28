// ES8311 音訊晶片驅動，取自微雪 ESP32-S3-RGB-Matrix 範例 09_Music_Player
// https://github.com/waveshareteam/ESP32-S3-RGB-Matrix （Apache License 2.0）
#include "es8311.h"

static const coeff_div_t coeff_div[] = {
  {11289600, 44100, 0x01, 0x00, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
  {5644800,  44100, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
  {2822400,  44100, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
  {1411200,  44100, 0x01, 0x03, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
  {12288000, 48000, 0x01, 0x00, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
  {18432000, 48000, 0x03, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
  {6144000,  48000, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
  {3072000,  48000, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
  {1536000,  48000, 0x01, 0x03, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10}
};

ES8311::ES8311(TwoWire *wire_instance)
{
  _wire = wire_instance;
}

ES8311::~ES8311()
{
  if (_wire != nullptr) {
    _wire->end();
  }
}

int ES8311::get_coeff(uint32_t mclk, uint32_t rate)
{
  size_t index = 0;
  while (index < (sizeof(coeff_div) / sizeof(coeff_div[0]))) {
    if (coeff_div[index].mclk == mclk && coeff_div[index].rate == rate) {
      return static_cast<int>(index);
    }

    ++index;
  }

  return -1;
}

bool ES8311::begin(int32_t sda, int32_t scl, uint32_t frequency)
{
  if (_wire == nullptr) {
    return false;
  }

  if (sda < 0 || scl < 0) {
    return false;
  }

  if (!_wire->begin(sda, scl, frequency)) {
    return false;
  }

  _wire->beginTransmission(ES8311_ADDR);
  if (_wire->endTransmission() != 0) {
    _wire->end();
    return false;
  }

  bool ok = true;
  uint8_t reg = 0;

  ok &= WriteReg(0x00, 0x1F);
  delay(20);
  ok &= WriteReg(0x00, 0x00);
  ok &= WriteReg(0x00, 0x80);
  ok &= WriteReg(0x01, 0x3F);

  reg = ReadReg(0x06);
  reg &= ~(1U << 5);
  ok &= WriteReg(0x06, reg);

  ok &= setSampleRate(ES8311_SAMPLE_RATE48);
  ok &= setBitsPerSample(ES8311_BITS_PER_SAMPLE16);

  ok &= WriteReg(0x0D, 0x01);
  ok &= WriteReg(0x0E, 0x02);
  ok &= WriteReg(0x12, 0x00);
  ok &= WriteReg(0x13, 0x10);
  ok &= WriteReg(0x1C, 0x6A);
  ok &= WriteReg(0x37, 0x08);

  return ok;
}

bool ES8311::setVolume(uint8_t volume)
{
  if (volume > 100) {
    volume = 100;
  }

  int reg32 = 0;
  if (volume != 0) {
    reg32 = ((volume * 256) / 100) - 1;
  }

  return WriteReg(0x32, static_cast<uint8_t>(reg32));
}

uint8_t ES8311::getVolume()
{
  const uint8_t reg32 = ReadReg(0x32);
  if (reg32 == 0) {
    return 0;
  }

  return static_cast<uint8_t>(((reg32 * 100) / 256) + 1);
}

bool ES8311::setSampleRate(uint32_t sample_rate)
{
  _mclk_hz = sample_rate * 256;
  if (sample_rate > 64000) {
    _mclk_hz /= 2;
  }

  const int coeff = get_coeff(_mclk_hz, sample_rate);
  if (coeff < 0) {
    return false;
  }

  const coeff_div_t &selected = coeff_div[coeff];
  bool ok = true;
  uint8_t reg = ReadReg(0x02);
  reg |= (selected.pre_div - 1) << 5;
  reg |= selected.pre_multi << 3;
  ok &= WriteReg(0x02, reg);

  const uint8_t reg03 = (selected.fs_mode << 6) | selected.adc_osr;
  ok &= WriteReg(0x03, reg03);
  ok &= WriteReg(0x04, selected.dac_osr);

  const uint8_t reg05 = ((selected.adc_div - 1) << 4) | (selected.dac_div - 1);
  ok &= WriteReg(0x05, reg05);

  reg = ReadReg(0x06);
  reg &= 0xE0;
  if (selected.bclk_div < 19) {
    reg |= (selected.bclk_div - 1);
  } else {
    reg |= selected.bclk_div;
  }
  ok &= WriteReg(0x06, reg);

  reg = ReadReg(0x07);
  reg &= 0xC0;
  reg |= selected.lrck_h;
  ok &= WriteReg(0x07, reg);
  ok &= WriteReg(0x08, selected.lrck_l);

  return ok;
}

bool ES8311::setBitsPerSample(uint8_t bps)
{
  uint8_t reg09 = ReadReg(0x09);
  uint8_t reg0A = ReadReg(0x0A);

  switch (bps) {
    case 16:
      reg09 |= (3 << 2);
      reg0A |= (3 << 2);
      break;
    case 18:
      reg09 |= (2 << 2);
      reg0A |= (2 << 2);
      break;
    case 20:
      reg09 |= (1 << 2);
      reg0A |= (1 << 2);
      break;
    case 24:
      reg09 |= (0 << 2);
      reg0A |= (0 << 2);
      break;
    case 32:
      reg09 |= (4 << 2);
      reg0A |= (4 << 2);
      break;
    default:
      return false;
  }

  bool ok = true;
  ok &= WriteReg(0x09, reg09);
  ok &= WriteReg(0x0A, reg0A);
  return ok;
}

bool ES8311::enableMicrophone(bool enable)
{
  uint8_t reg = 0x1A;
  if (enable) {
    reg |= (1U << 6);
  }

  bool ok = true;
  ok &= WriteReg(0x17, 0xC8);
  ok &= WriteReg(0x14, reg);
  return ok;
}

bool ES8311::setMicrophoneGain(uint8_t gain)
{
  if (gain > 7) {
    gain = 7;
  }

  uint8_t reg = ReadReg(0x16);
  reg &= 0xF8;
  reg |= gain;
  return WriteReg(0x16, reg);
}

uint8_t ES8311::getMicrophoneGain()
{
  return ReadReg(0x16) & 0x07;
}

bool ES8311::WriteReg(uint8_t reg, uint8_t val)
{
  _wire->beginTransmission(ES8311_ADDR);
  _wire->write(reg);
  _wire->write(val);
  return _wire->endTransmission() == 0;
}

uint8_t ES8311::ReadReg(uint8_t reg)
{
  _wire->beginTransmission(ES8311_ADDR);
  _wire->write(reg);
  _wire->endTransmission(false);

  uint8_t val = 0;
  _wire->requestFrom(uint16_t(ES8311_ADDR), static_cast<uint8_t>(1), true);
  if (_wire->available() >= 1) {
    val = _wire->read();
  }
  return val;
}

void ES8311::read_all()
{
  uint8_t reg = 0;
  while (reg < 0x4A) {
    Serial.printf("0x%02X: 0x%02X\n", reg, ReadReg(reg));
    ++reg;
  }
}
