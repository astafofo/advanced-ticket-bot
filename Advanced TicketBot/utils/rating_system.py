import discord
import logging
from datetime import datetime, timezone
from utils.helpers import utc_to_gmt

logger = logging.getLogger('discord')

class RatingView(discord.ui.View):
    def __init__(self, bot, ticket_number, creator_id, closer_name, guild_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.ticket_number = ticket_number
        self.creator_id = creator_id
        self.closer_name = closer_name
        self.guild_id = guild_id
        
        self._timeout = None

    @discord.ui.select(
        placeholder="⭐ Rate your support experience...",
        options=[
            discord.SelectOption(
                label="1 Star - Poor",
                value="1",
                emoji="⭐",
                description="Very unsatisfied with the support"
            ),
            discord.SelectOption(
                label="2 Stars - Fair",
                value="2",
                emoji="⭐",
                description="Not satisfied with the support"
            ),
            discord.SelectOption(
                label="3 Stars - Good",
                value="3",
                emoji="⭐",
                description="Satisfied with the support"
            ),
            discord.SelectOption(
                label="4 Stars - Very Good",
                value="4",
                emoji="⭐",
                description="Very satisfied with the support"
            ),
            discord.SelectOption(
                label="5 Stars - Excellent",
                value="5",
                emoji="⭐",
                description="Extremely satisfied with the support"
            )
        ],
        custom_id="rating_select_new"
    )
    async def rating_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        try:
            if interaction.user.id != self.creator_id:
                await interaction.response.send_message(
                    "<:icons_Wrong:1382701332955402341> Only the ticket creator can rate this ticket.",
                    ephemeral=True
                )
                return

            async with self.bot.db.cursor() as cur:
                await cur.execute("""
                    SELECT rating FROM ticket_ratings 
                    WHERE guild_id = ? AND ticket_number = ? AND user_id = ?
                """, (self.guild_id, self.ticket_number, self.creator_id))
                existing_rating = await cur.fetchone()

                if existing_rating:
                    await interaction.response.send_message(
                        "<:icons_Wrong:1382701332955402341> You have already submitted a rating for this ticket.",
                        ephemeral=True
                    )
                    return

            rating = int(select.values[0])
            modal = FeedbackModal(self.bot, self.ticket_number, self.creator_id, self.closer_name, self.guild_id, rating, self)
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"Error in rating select: {e}")
            try:
                await interaction.response.send_message(
                    "<:icons_Wrong:1382701332955402341> An error occurred while processing your rating. Please try again.",
                    ephemeral=True
                )
            except:
                pass

class FeedbackModal(discord.ui.Modal):
    def __init__(self, bot, ticket_number, creator_id, closer_name, guild_id, rating, rating_view=None):
        super().__init__(title="⭐ Support Feedback")
        self.bot = bot
        self.ticket_number = ticket_number
        self.creator_id = creator_id
        self.closer_name = closer_name
        self.guild_id = guild_id
        self.rating = rating
        self.rating_view = rating_view

    staff_member = discord.ui.TextInput(
        label="Which staff member helped you?",
        placeholder="Enter the name of the staff member who assisted you...",
        max_length=100,
        required=False
    )

    feedback = discord.ui.TextInput(
        label="Additional Comments (Optional)",
        style=discord.TextStyle.paragraph,
        placeholder="Share your experience, suggestions for improvement, or any other feedback...",
        max_length=1000,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            staff_name = self.staff_member.value.strip() if self.staff_member.value else None
            feedback_text = self.feedback.value.strip() if self.feedback.value else None

            async with self.bot.db.cursor() as cur:
                await cur.execute("""
                    INSERT OR REPLACE INTO ticket_ratings 
                    (guild_id, ticket_number, user_id, rating, feedback, staff_member, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.guild_id, 
                    self.ticket_number, 
                    self.creator_id, 
                    self.rating, 
                    feedback_text, 
                    staff_name, 
                    datetime.now(timezone.utc).isoformat()
                ))
                await self.bot.db.commit()
            
            if self.rating_view:
                for item in self.rating_view.children:
                    item.disabled = True

            stars = "⭐" * self.rating
            current_time = utc_to_gmt(discord.utils.utcnow())

            confirmation_embed = discord.Embed(
                title="⭐ Thank You for Your Feedback!",
                description=f"**Your rating and feedback have been submitted successfully.**\n\n"
                           f"**Rating:** {stars} ({self.rating}/5)\n"
                           f"**Ticket:** #{self.ticket_number:04d}\n"
                           f"**Closed by:** {self.closer_name}",
                color=0x00D4FF,
                timestamp=current_time
            )

            if staff_name:
                confirmation_embed.add_field(
                    name="👤 Staff Member",
                    value=f"*{staff_name}*",
                    inline=True
                )

            if feedback_text:
                confirmation_embed.add_field(
                    name="💬 Your Feedback",
                    value=f"*{feedback_text[:200]}{'...' if len(feedback_text) > 200 else ''}*",
                    inline=False
                )

            confirmation_embed.add_field(
                name="🙏 Thank You",
                value="Your feedback helps us improve our service quality and train our support team!",
                inline=False
            )

            confirmation_embed.set_footer(text="Support System • Rating Complete")
            await interaction.response.send_message(embed=confirmation_embed, ephemeral=True)

            await self.log_rating(staff_name, feedback_text, current_time)

        except Exception as e:
            logger.error(f"Error submitting feedback: {e}")
            try:
                error_embed = discord.Embed(
                    title="❌ Feedback Submission Error",
                    description="An error occurred while submitting your feedback. Please try again later.",
                    color=0xFF6B6B
                )
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except:
                logger.error("Failed to send error message")

    async def log_rating(self, staff_name, feedback_text, current_time):
        try:
            async with self.bot.db.cursor() as cur:
                await cur.execute("SELECT log_channel_id FROM tickets WHERE guild_id = ?", (self.guild_id,))
                result = await cur.fetchone()

                if not result or not result[0]:
                    return

                log_channel = self.bot.get_channel(result[0])
                if not log_channel:
                    return

            user = self.bot.get_user(self.creator_id)
            stars = "⭐" * self.rating

            rating_colors = {1: 0xFF4444, 2: 0xFF8800, 3: 0xFFDD00, 4: 0x88DD00, 5: 0x00DD00}

            log_embed = discord.Embed(
                title="⭐ Support Rating Received",
                description=f"**A customer has rated their support experience**\n\n"
                           f"**Rating:** {stars} ({self.rating}/5 stars)\n"
                           f"**Ticket:** #{self.ticket_number:04d}\n"
                           f"**Customer:** {user.display_name if user else 'Unknown User'} ({self.creator_id})",
                color=rating_colors.get(self.rating, 0x00D4FF),
                timestamp=current_time
            )

            log_embed.add_field(
                name="📋 Ticket Details",
                value=f"**Ticket Number:** #{self.ticket_number:04d}\n"
                      f"**Closed by:** {self.closer_name}\n"
                      f"**Rating Date:** {discord.utils.format_dt(current_time, 'F')}",
                inline=True
            )

            if staff_name:
                log_embed.add_field(
                    name="👤 Staff Recognition",
                    value=f"**Mentioned Staff:** {staff_name}\n"
                          f"**Performance:** {stars}",
                    inline=True
                )

            if feedback_text:
                log_embed.add_field(
                    name="💬 Customer Feedback",
                    value=f"*\"{feedback_text}\"*",
                    inline=False
                )

            async with self.bot.db.cursor() as cur:
                await cur.execute("""
                    SELECT AVG(rating), COUNT(*) FROM ticket_ratings 
                    WHERE guild_id = ? AND created_at >= datetime('now', '-30 days')
                """, (self.guild_id,))
                avg_rating, total_ratings = await cur.fetchone()

                if avg_rating:
                    log_embed.add_field(
                        name="📊 Rating Statistics (Last 30 Days)",
                        value=f"**Average Rating:** {avg_rating:.1f}/5.0\n"
                              f"**Total Ratings:** {total_ratings}",
                        inline=False
                    )

            log_embed.set_footer(text="Support System • Customer Rating")
            if user:
                log_embed.set_thumbnail(url=user.display_avatar.url)

            await log_channel.send(embed=log_embed)

        except Exception as e:
            logger.error(f"Error logging rating: {e}")

async def send_rating_request(bot, user, ticket_number, closer_name, guild_id):
    """Send a rating request to the user via DM"""
    try:
        if not user:
            logger.warning(f"Cannot send rating request - user not found")
            return False

        async with bot.db.cursor() as cur:
            await cur.execute("""
                SELECT rating FROM ticket_ratings 
                WHERE guild_id = ? AND ticket_number = ? AND user_id = ?
            """, (guild_id, ticket_number, user.id))
            existing_rating = await cur.fetchone()

            if existing_rating:
                logger.info(f"User {user.id} has already rated ticket #{ticket_number:04d}")
                return True

        current_time = utc_to_gmt(discord.utils.utcnow())

        rating_embed = discord.Embed(
            title="⭐ Rate Your Support Experience",
            description=f"**Your ticket #{ticket_number:04d} has been closed successfully!**\n\n"
                       f"We'd love to hear about your experience with our support team. "
                       f"Your feedback helps us improve our service quality.\n\n"
                       f"**Ticket Details:**\n"
                       f"📋 **Ticket Number:** #{ticket_number:04d}\n"
                       f"👤 **Closed by:** {closer_name}\n"
                       f"📅 **Closed on:** {current_time.strftime('%B %d, %Y at %I:%M %p GMT')}\n\n"
                       f"**Please select your rating below:**",
            color=0x00D4FF,
            timestamp=current_time
        )

        rating_embed.add_field(
            name="🎯 Why Your Feedback Matters",
            value="• Helps us train our support team\n"
                  "• Improves our service quality\n"
                  "• Recognizes outstanding staff performance\n"
                  "• Shapes our support policies",
            inline=False
        )

        rating_embed.set_footer(text="Support System • Your Opinion Matters")

        view = RatingView(bot, ticket_number, user.id, closer_name, guild_id)
        message = await user.send(embed=rating_embed, view=view)

        logger.info(f"✅ Rating request sent successfully to user {user.id} for ticket #{ticket_number:04d}")
        return True

    except discord.Forbidden:
        logger.warning(f"❌ Could not send rating request to user {user.id} - DMs disabled")
        return False
    except Exception as e:
        logger.error(f"❌ Error sending rating request to user {user.id}: {e}")
        return False