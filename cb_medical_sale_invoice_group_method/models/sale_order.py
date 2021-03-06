# Copyright 2017 Creu Blanca
# Copyright 2017 Eficent Business and IT Consulting Services, S.L.
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).

from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    preinvoice_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("to preinvoice", "To Prenvoice"),
            ("preinvoiced", "Prenvoiced"),
        ],
        store=True,
        compute="_compute_preinvoice_status",
    )

    @api.depends(
        "state",
        "order_line.invoice_status",
        "third_party_order",
        "order_line.invoice_group_method_id",
        "order_line.invoice_group_method_id.invoice_by_preinvoice",
        "order_line.qty_invoiced",
        "order_line.product_uom_qty",
        "order_line.preinvoice_group_id",
    )
    def _compute_preinvoice_status(self):
        for order in self:
            if order.state not in ["draft", "cancel"]:
                if order.third_party_order or all(
                    line.preinvoice_group_id
                    for line in order.order_line.filtered(
                        lambda r: r.invoice_group_method_id.invoice_by_preinvoice
                        or r.qty_invoiced == r.product_uom_qty
                    )
                ):
                    order.preinvoice_status = "preinvoiced"
                else:
                    order.preinvoice_status = "to preinvoice"
            else:
                order.preinvoice_status = "draft"

    def action_invoice_by_group_create(self, invoice_group_method_id, company):
        journal = invoice_group_method_id.get_journal(company)
        ctx = {"invoice_group_method_id": invoice_group_method_id.id}
        if journal:
            ctx["default_journal_id"] = journal.id
        invoices = self.with_context(**ctx).action_invoice_create()
        return invoices

    @api.model
    def _get_invoice_group_key(self, order):
        if order.coverage_agreement_id:
            return (
                order.partner_invoice_id.id,
                order.currency_id.id,
                order.company_id.id,
                order.coverage_agreement_id.id,
                order.coverage_template_id.id,
            )
        return super()._get_invoice_group_key(order)

    @api.model
    def _get_invoice_group_line_key(self, line):
        if line.invoice_group_method_id and not self.env.context.get(
            "no_split_invoices", False
        ):
            return (
                line.order_id.partner_invoice_id.id,
                line.order_id.currency_id.id,
                line.order_id.company_id.id,
                line.order_id.coverage_agreement_id.id,
                line.invoice_group_method_id.id,
                line.coverage_template_id.id,
            )
        return super()._get_invoice_group_line_key(line)

    @api.model
    def _get_draft_invoices(self, invoices, references):
        invoices, references = super()._get_draft_invoices(
            invoices, references
        )
        method = self.env.context.get("invoice_group_method_id", False)
        if method and self.env.context.get("cb_merge_draft_invoice", False):
            domain = [
                ("state", "=", "draft"),
                ("invoice_group_method_id", "=", method),
            ]
            companies = self.env.context.get("companies")
            if companies:
                domain.append(("company_id", "in", companies))
            customers = self.env.context.get("customers")
            if customers:
                domain.append(("partner_id", "in", customers))
            draft_inv = self.env["account.invoice"].search(domain)
            for inv in draft_inv:
                for line in inv.invoice_line_ids.mapped("sale_line_ids"):
                    ref_order = self._get_invoice_group_line_key(line)
                    references[inv] = line.order_id
                    invoices[ref_order] = inv
        return invoices, references

    @api.multi
    def _prepare_invoice(self):
        res = super()._prepare_invoice()
        if self.encounter_id and self.coverage_agreement_id:
            res["agreement_id"] = self.coverage_agreement_id.id
        return res
