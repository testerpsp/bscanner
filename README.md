# BScanner

# BScanner (Blockchain Wallet Scanner)

Script Python sederhana untuk scan saldo wallet **EVM (0x...)** dan **IBC/Cosmos (cosmos1...)** langsung dari HP menggunakan Termux atau Pydroid3.  

Repo: [https://github.com/testerpsp/bscanner](https://github.com/testerpsp/bscanner)

---

## Cara Install di Termux (Android)

1. **Update Termux & Install Python + Git**
   ```bash
   pkg update && pkg upgrade -y
   pkg install python git -y

2. Clone repo

       git clone https://github.com/testerpsp/bscanner.git
       cd bscanner

3. install library python

       pip install -r requirements.txt

4. RUN

       python bscanner.py


