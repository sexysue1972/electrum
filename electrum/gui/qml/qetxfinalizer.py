from decimal import Decimal

from PyQt5.QtCore import pyqtProperty, pyqtSignal, pyqtSlot, QObject

from electrum.logging import get_logger
from electrum.i18n import _
from electrum.transaction import PartialTxOutput
from electrum.util import NotEnoughFunds, profiler

from .qewallet import QEWallet
from .qetypes import QEAmount

class QETxFinalizer(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tx = None

    _logger = get_logger(__name__)

    _address = ''
    _amount = QEAmount()
    _fee = QEAmount()
    _feeRate = ''
    _wallet = None
    _valid = False
    _sliderSteps = 0
    _sliderPos = 0
    _method = -1
    _warning = ''
    _target = ''
    _rbf = False
    _outputs = []
    config = None

    validChanged = pyqtSignal()
    @pyqtProperty(bool, notify=validChanged)
    def valid(self):
        return self._valid

    walletChanged = pyqtSignal()
    @pyqtProperty(QEWallet, notify=walletChanged)
    def wallet(self):
        return self._wallet

    @wallet.setter
    def wallet(self, wallet: QEWallet):
        if self._wallet != wallet:
            self._wallet = wallet
            self.config = self._wallet.wallet.config
            self.read_config()
            self.walletChanged.emit()

    addressChanged = pyqtSignal()
    @pyqtProperty(str, notify=addressChanged)
    def address(self):
        return self._address

    @address.setter
    def address(self, address):
        if self._address != address:
            self._address = address
            self.addressChanged.emit()

    amountChanged = pyqtSignal()
    @pyqtProperty(QEAmount, notify=amountChanged)
    def amount(self):
        return self._amount

    @amount.setter
    def amount(self, amount):
        if self._amount != amount:
            self._logger.debug(str(amount))
            self._amount = amount
            self.amountChanged.emit()

    feeChanged = pyqtSignal()
    @pyqtProperty(QEAmount, notify=feeChanged)
    def fee(self):
        return self._fee

    @fee.setter
    def fee(self, fee):
        if self._fee != fee:
            self._fee = fee
            self.feeChanged.emit()

    feeRateChanged = pyqtSignal()
    @pyqtProperty(str, notify=feeRateChanged)
    def feeRate(self):
        return self._feeRate

    @feeRate.setter
    def feeRate(self, feeRate):
        if self._feeRate != feeRate:
            self._feeRate = feeRate
            self.feeRateChanged.emit()

    targetChanged = pyqtSignal()
    @pyqtProperty(str, notify=targetChanged)
    def target(self):
        return self._target

    @target.setter
    def target(self, target):
        if self._target != target:
            self._target = target
            self.targetChanged.emit()

    rbfChanged = pyqtSignal()
    @pyqtProperty(bool, notify=rbfChanged)
    def rbf(self):
        return self._rbf

    @rbf.setter
    def rbf(self, rbf):
        if self._rbf != rbf:
            self._rbf = rbf
            self.update()
            self.rbfChanged.emit()

    outputsChanged = pyqtSignal()
    @pyqtProperty('QVariantList', notify=outputsChanged)
    def outputs(self):
        return self._outputs

    @outputs.setter
    def outputs(self, outputs):
        if self._outputs != outputs:
            self._outputs = outputs
            self.outputsChanged.emit()

    warningChanged = pyqtSignal()
    @pyqtProperty(str, notify=warningChanged)
    def warning(self):
        return self._warning

    @warning.setter
    def warning(self, warning):
        if self._warning != warning:
            self._warning = warning
            self.warningChanged.emit()

    sliderStepsChanged = pyqtSignal()
    @pyqtProperty(int, notify=sliderStepsChanged)
    def sliderSteps(self):
        return self._sliderSteps

    sliderPosChanged = pyqtSignal()
    @pyqtProperty(int, notify=sliderPosChanged)
    def sliderPos(self):
        return self._sliderPos

    @sliderPos.setter
    def sliderPos(self, sliderPos):
        if self._sliderPos != sliderPos:
            self._sliderPos = sliderPos
            self.save_config()
            self.sliderPosChanged.emit()

    methodChanged = pyqtSignal()
    @pyqtProperty(int, notify=methodChanged)
    def method(self):
        return self._method

    @method.setter
    def method(self, method):
        if self._method != method:
            self._method = method
            self.update_slider()
            self.methodChanged.emit()
            self.save_config()

    def get_method(self):
        dynfees = self._method > 0
        mempool = self._method == 2
        return dynfees, mempool

    def update_slider(self):
        dynfees, mempool = self.get_method()
        maxp, pos, fee_rate = self.config.get_fee_slider(dynfees, mempool)
        self._sliderSteps = maxp
        self._sliderPos = pos
        self.sliderStepsChanged.emit()
        self.sliderPosChanged.emit()

    def read_config(self):
        mempool = self.config.use_mempool_fees()
        dynfees = self.config.is_dynfee()
        self._method = (2 if mempool else 1) if dynfees else 0
        self.update_slider()
        self.methodChanged.emit()
        self.update()

    def save_config(self):
        value = int(self._sliderPos)
        dynfees, mempool = self.get_method()
        self.config.set_key('dynamic_fees', dynfees, False)
        self.config.set_key('mempool_fees', mempool, False)
        if dynfees:
            if mempool:
                self.config.set_key('depth_level', value, True)
            else:
                self.config.set_key('fee_level', value, True)
        else:
            self.config.set_key('fee_per_kb', self.config.static_fee(value), True)
        self.update()

    @profiler
    def make_tx(self):
        coins = self._wallet.wallet.get_spendable_coins(None)
        outputs = [PartialTxOutput.from_address_and_value(self.address, self._amount.satsInt)]
        tx = self._wallet.wallet.make_unsigned_transaction(coins=coins,outputs=outputs, fee=None,rbf=self._rbf)
        self._logger.debug('fee: %d, inputs: %d, outputs: %d' % (tx.get_fee(), len(tx.inputs()), len(tx.outputs())))
        self._logger.debug(repr(tx.outputs()))
        outputs = []
        for o in tx.outputs():
            outputs.append(o.to_json())
        self.outputs = outputs
        return tx

    @pyqtSlot()
    def update(self):
        try:
            # make unsigned transaction
            tx = self.make_tx()
        except NotEnoughFunds:
            self.warning = _("Not enough funds")
            self._valid = False
            self.validChanged.emit()
            return
        except Exception as e:
            self._logger.error(str(e))
            self.warning = repr(e)
            self._valid = False
            self.validChanged.emit()
            return

        self._tx = tx

        amount = self._amount.satsInt if not self._amount.isMax else tx.output_value()

        tx_size = tx.estimated_size()
        fee = tx.get_fee()
        feerate = Decimal(fee) / tx_size  # sat/byte

        self.fee = QEAmount(amount_sat=fee)
        self.feeRate = f'{feerate:.1f}'

        #TODO
        #x_fee = run_hook('get_tx_extra_fee', self._wallet.wallet, tx)
        fee_warning_tuple = self._wallet.wallet.get_tx_fee_warning(
            invoice_amt=amount, tx_size=tx_size, fee=fee)
        if fee_warning_tuple:
            allow_send, long_warning, short_warning = fee_warning_tuple
            self.warning = long_warning
        else:
            self.warning = ''

        target, tooltip, dyn = self.config.get_fee_target()
        self.target = target

        self._valid = True
        self.validChanged.emit()

    @pyqtSlot()
    def send_onchain(self):
        if not self._valid or not self._tx:
            self._logger.debug('no valid tx')
            return

        self._wallet.sign_and_broadcast(self._tx)
